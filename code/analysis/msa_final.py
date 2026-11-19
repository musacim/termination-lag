#!/usr/bin/env python3
"""mini-SWE-agent vs OpenHands, Qwen3-Coder-30B, SWE-bench Verified: table and figure.
usage: msa_final.py"""
import os
import json, glob, statistics as st, subprocess, sys
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
E = os.environ.get("TL_ROOT", "."); A = f"{E}/analysis"
rows = json.load(open(f"{A}/qwen3coder_verified_minisweagent_tasks.json"))
dedup = json.load(open(f"{A}/qwen3coder_verified_minisweagent_dedup.json"))
for r in rows:
    if r["iid"] in dedup:
        key = json.load(open(f"{E}/tasks/swebench_verified_meta.json"))[r["iid"]]["key"]; conv = None; mx = -1
        for l in open(f"{E}/{dedup[r['iid']]}/steps.jsonl"):
            x = json.loads(l)
            if "head" in x and key in " ".join(x["head"].split()): conv = x["conv"]
            if conv and x["conv"] == conv: mx = max(mx, x["step"])
        r["stop"] = mx + 1
        r["ms"] = {k: v for k, v in r["ms"].items() if int(k) <= r["stop"]}
        fc = [int(k) for k, v in r["ms"].items() if v]; r["first_correct"] = min(fc) if fc else None
json.dump(rows, open(f"{A}/qwen3coder_verified_minisweagent_tasks.json", "w"))
subprocess.run([sys.executable, f"{A}/tl_plot.py", "qwen3coder_verified_minisweagent", "Qwen3-Coder-30B · mini-SWE-agent · SWE-bench Verified"],
               stdout=subprocess.DEVNULL, check=True)
m = {r["iid"]: r for r in rows}; o = {r["iid"]: r for r in json.load(open(f"{A}/qwen3coder_verified_tasks.json"))}
ids = sorted(set(m) & set(o))
p90 = lambda v: sorted(v)[int(.9 * (len(v) - 1))]


def stats(R):
    rr = [R[i] for i in ids]; n = len(rr)
    sol = [r for r in rr if r["final"] and r["first_correct"] and r["stop"]]
    gap = [r["stop"] - r["first_correct"] for r in sol]
    base = sum(r["stop"] or 0 for r in rr)
    orc = sum(r["stop"] - r["first_correct"] for r in rr if r["first_correct"] and r["stop"] and r["first_correct"] < r["stop"])
    return {"Solved": f"{100*sum(r['final'] for r in rr)/n:.1f}%",
            "Reach a correct patch at some step": f"{100*sum(1 for r in rr if r['first_correct'])/n:.1f}%",
            "Agent stops on its own": f"{100*sum(r['finished'] for r in rr)/n:.1f}%",
            "First correct step, median (solved runs)": f"{st.median([r['first_correct'] for r in sol]):.0f}",
            "Agent's own stop, median (solved runs)": f"{st.median([r['stop'] for r in sol]):.0f}",
            "Steps after the first correct patch, median / p90": f"{st.median(gap):.0f} / {p90(gap)}",
            "Share of each solved trajectory after the fix, median": f"{st.median([100*g/r['stop'] for g, r in zip(gap, sol)]):.0f}%",
            "Oracle stop: steps saved (all runs)": f"{100*orc/base:.1f}%",
            "Steps per task, mean (all runs)": f"{base/n:.1f}"}


so, sm = stats(o), stats(m)
print(f"{len(ids)} tasks graded for both\n{'':56s} {'OpenHands':>12s} {'mini-SWE-agent':>15s}")
for k in so:
    print(f"{k:56s} {so[k]:>12s} {sm[k]:>15s}")
both = sum(m[i]["final"] and o[i]["final"] for i in ids)
print(f"solved by both {both}, only OpenHands {sum(o[i]['final'] and not m[i]['final'] for i in ids)}, "
      f"only mini-SWE-agent {sum(m[i]['final'] and not o[i]['final'] for i in ids)}")
fig, axs = plt.subplots(1, 2, figsize=(14, 5))
for ax, f, t in ((axs[0], f"{A}/qwen3coder_verified_waste.png", "OpenHands"), (axs[1], f"{A}/qwen3coder_verified_minisweagent_waste.png", "mini-SWE-agent")):
    ax.imshow(plt.imread(f)); ax.axis("off"); ax.set_title(t, fontsize=12)
fig.tight_layout(); fig.savefig(f"{A}/waste_plots/qwen3coder_verified_minisweagent_vs_qwen3coder_verified_waste.png", dpi=150)
print(f"figure: {A}/waste_plots/qwen3coder_verified_minisweagent_vs_qwen3coder_verified_waste.png")
