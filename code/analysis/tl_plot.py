#!/usr/bin/env python3
"""Termination-lag numbers and figures for one run.
usage: tl_plot.py <run> <title>"""
import json, os, statistics as st, sys
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
TAG, TITLE = sys.argv[1], sys.argv[2]
A = os.path.join(os.environ.get("TL_ROOT", "."), "analysis")
rows = json.load(open(f"{A}/{TAG}_tasks.json")); n = len(rows)
MX = max(r["stop"] or 0 for r in rows); MX = 100 if MX <= 100 else 150 if MX <= 150 else 250
N = list(range(1, MX + 1))
def at(r, k):
    return bool(r["ms"][str(k)]) if str(k) in r["ms"] and k < (r["stop"] or MX) else r["final"]
rate = [100 * sum(at(r, k) for r in rows) / n for k in N]
def style(ax, ylab, ymax):
    ax.set_xlabel("Step"); ax.set_ylabel(ylab); ax.set_xticks(range(0, MX + 1, 10 if MX == 100 else 25)); ax.set_xlim(0, MX + 1); ax.set_ylim(0, ymax)
    ax.grid(axis="y", color="#e5e5e5", lw=0.8); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
cum = lambda v: [100 * sum(x <= k for x in v) / n for k in N]
nat = [r for r in rows if r["first_correct"] is not None and r["finished"] and r["stop"]]
def q(v): v = sorted(v); return f"median {st.median(v):.0f}, mean {st.mean(v):.1f}, p90 {v[int(.9*(len(v)-1))]}"
print(f"tasks {n}; final resolved {sum(r['final'] for r in rows)} ({100*sum(r['final'] for r in rows)/n:.1f}%); "
      f"ever correct {sum(r['first_correct'] is not None for r in rows)}; stopped on their own {sum(r['finished'] for r in rows)}")
print(f"solved tasks that stopped on their own ({len(nat)}): first edit {q([r['first_edit'] for r in nat if r['first_edit']])}")
print(f"  first correct {q([r['first_correct'] for r in nat])}; stop {q([r['stop'] for r in nat])}")
print(f"  first edit -> first correct {q([r['first_correct'] - r['first_edit'] for r in nat if r['first_edit']])}")
print(f"  first correct -> stop {q([r['stop'] - r['first_correct'] for r in nat])}")
def outcome(r, s):
    if s is None or not r["stop"] or s >= r["stop"]: return r["final"], r["stop"] or 0
    return bool(r["ms"].get(str(s))), s
base = sum(r["stop"] or 0 for r in rows)
pol = [("Agent's own stop", lambda r: None), ("Oracle: first correct patch", lambda r: r["first_correct"])]
print(f"\n{'policy':30s} {'solved':>11s} {'steps saved':>16s}   own-run saved all tasks mean/median | solved tasks mean/median")
for name, f in pol:
    ok = used = 0; fr = []; frs = []
    for r in rows:
        o, s = outcome(r, f(r)); ok += o; used += s
        if r["stop"]:
            x = 100 * (r["stop"] - s) / r["stop"]; fr.append(x)
            if r["final"]: frs.append(x)
    print(f"{name:30s} {ok:4d} {100*ok/n:5.1f}% {base-used:7d} ({100*(base-used)/base:4.1f}%)   "
          f"{st.mean(fr):5.1f}% / {st.median(fr):5.1f}%  |  {st.mean(frs):5.1f}% / {st.median(frs):5.1f}%")
fig, ax = plt.subplots(figsize=(6, 3.6), dpi=150)
ax.plot(N, rate, color="#2a6fdb", lw=2)
for k in (30, 50, MX): ax.annotate(f"{rate[k-1]:.1f}%", (k, rate[k-1]), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9, color="#333")
style(ax, "Solve rate (%)", max(rate) * 1.25); ax.set_xlabel("Stop at step N")
ax.set_title(TITLE + f" · {n} tasks", fontsize=10, loc="left"); fig.tight_layout(); fig.savefig(f"{A}/{TAG}_stopcurve.png"); plt.close(fig)
fig, ax = plt.subplots(figsize=(6, 3.6), dpi=150)
for key, lab, col in (("first_edit", "first agent edit", "#9aa5b1"), ("first_correct", "first correct patch", "#2a6fdb"), ("stop", "agent stops", "#d1495b")):
    ax.plot(N, cum([r[key] for r in nat if r[key]]), color=col, lw=2, label=lab)
style(ax, f"Share of all {n} tasks (%)", max(rate) * 1.2); ax.legend(frameon=False, fontsize=9, loc="lower right")
ax.set_title(TITLE + " · tasks the agent solved", fontsize=10, loc="left"); fig.tight_layout(); fig.savefig(f"{A}/{TAG}_timeline.png"); plt.close(fig)
fig, ax = plt.subplots(figsize=(6.4, 3.8), dpi=150)
ax.plot(N, cum([r["stop"] for r in rows if r["stop"] and r["finished"]]), color="#d1495b", lw=2, label="agent stopped on its own (all tasks)")
ax.plot(N, cum([r["first_correct"] for r in rows if r["first_correct"]]), color="#2a6fdb", lw=2, label="first correct patch reached")
ax.plot(N, rate, color="#333333", lw=1.3, ls="--", label="solve rate if stopped at N")
ax.plot(N, cum([r["stop"] for r in rows if r["stop"] and r["finished"] and r["final"]]), color="#e8a33d", lw=2, label="solved and stopped (banked)")
style(ax, f"Share of all {n} tasks (%)", 102); ax.legend(frameon=False, fontsize=8, loc="upper left")
ax.set_title(TITLE + f" · all {n} tasks", fontsize=10, loc="left"); fig.tight_layout(); fig.savefig(f"{A}/{TAG}_stops.png"); plt.close(fig)
print(f"\nplots: {A}/{TAG}_stopcurve.png {A}/{TAG}_timeline.png {A}/{TAG}_stops.png")
sol = [r for r in rows if r["final"] and r["first_correct"] and r["stop"]]
fc_v = [r["first_correct"] for r in sol]; st_v = [r["stop"] for r in sol]
yc, ys = cum(fc_v), cum(st_v); waste = sum(s - f for f, s in zip(fc_v, st_v))
fig, ax = plt.subplots(figsize=(6.6, 3.9), dpi=170)
ax.fill_between(N, ys, yc, where=[a >= b for a, b in zip(yc, ys)], color="#d1495b", alpha=0.16, lw=0, interpolate=True, label="Work After the Fix")
import os
FP = json.load(open(f"{A}/first_patch.json")).get(TAG) if os.path.exists(f"{A}/first_patch.json") else None
if FP:
    fpd = {x["iid"]: x["first_patch"] for x in FP}
    ax.plot(N, cum([fpd[r["iid"]] for r in sol if r["iid"] in fpd]), color="#8a8a8a", lw=2.2, label="First Patch")
ax.plot(N, yc, color="#2a6fdb", lw=2.2, label="First Correct Patch")
ax.plot(N, ys, color="#e8a33d", lw=2.2, label="Agent Self-Termination")
yh = yc[-1] / 2
gap = st.median([s - f for f, s in zip(fc_v, st_v)]); xa = next(k for k, v in zip(N, yc) if v >= yh); xb = xa + gap
ax.annotate("", xy=(xb, yh), xytext=(xa, yh), arrowprops=dict(arrowstyle="<->", color="#333", lw=1.3))
ax.text((xa + xb) / 2, yh + 1.2, f"{gap:.0f} steps", ha="center", va="bottom", fontsize=9, color="#333")
xm = next(k for k, v in zip(N, yc) if v >= yc[-1] * 0.8)
own = [100 * (s - f) / s for f, s in zip(fc_v, st_v)]
ax.annotate(f"wasted: {st.median(own):.0f}% of each\ntrajectory's steps (median)",
            xy=((xa + xb) / 2, yh * 1.3), xytext=(0.61 * MX, yc[-1] * 1.07), fontsize=8.5, color="#a33",
            arrowprops=dict(arrowstyle="->", color="#a33", lw=1, connectionstyle="arc3,rad=0.25"))
hh, ll = ax.get_legend_handles_labels()
style(ax, "Tasks (%)", yc[-1] * 1.25); ax.legend(hh[1:] + hh[:1], ll[1:] + ll[:1], frameon=False, fontsize=9, loc=os.environ.get("TL_LEGEND", "lower right"))
ax.set_title(TITLE, fontsize=10, loc="left"); fig.tight_layout(); fig.savefig(f"{A}/{TAG}_waste.png")
print(f"waste plot: {len(sol)} solved tasks, ends at {yc[-1]:.1f}% / {ys[-1]:.1f}%, gap median {gap:.0f}, wasted median {st.median(own):.0f}%"); plt.close(fig)
print(f"{A}/{TAG}_waste.png")
