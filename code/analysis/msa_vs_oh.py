#!/usr/bin/env python3
"""mini-SWE-agent vs OpenHands: steps, tokens and time per task.
usage: msa_vs_oh.py"""
import os
import collections, glob, json, statistics as st
E = os.environ.get("TL_ROOT", ".")
KEYS = {i: m["key"] for i, m in json.load(open(f"{E}/tasks/swebench_verified_meta.json")).items()}


def per_task(globs):
    out = {}
    for f in [x for g in globs for x in glob.glob(f"{E}/{g}/steps.jsonl")]:
        conv, title, recs = {}, set(), []
        for l in open(f):
            d = json.loads(l)
            if d.get("async"):
                continue
            if "head" in d:
                h = " ".join(d["head"].split()); hit = [i for i, k in KEYS.items() if k in h]
                if len(hit) == 1:
                    conv[d["conv"]] = hit[0]
                if d["head"].startswith("Generate a title"):
                    title.add(d["conv"])
            recs.append(d)
        agg = collections.defaultdict(lambda: {"calls": 0, "p": 0, "c": 0, "o": 0, "last_p": 0, "t0": 1e18, "t1": 0, "steps": -1})
        for d in recs:
            i = conv.get(d["conv"])
            if not i or d["conv"] in title or d.get("status") != 200:
                continue
            a = agg[i]; a["calls"] += 1; a["p"] += d.get("prompt_tokens") or 0; a["c"] += d.get("cached_tokens") or 0
            a["o"] += d.get("completion_tokens") or 0; a["t0"] = min(a["t0"], d["t0"]); a["t1"] = max(a["t1"], d.get("t1") or d["t0"])
            if d["step"] >= a["steps"]:
                a["steps"] = d["step"]; a["last_p"] = d.get("prompt_tokens") or 0
        out.update(agg)
    return out


msa = per_task(["runs/qwen3coder_verified_minisweagent"])
oh = per_task(["runs/qwen3coder_verified"])
done = {}
for f in glob.glob(f"{E}/runs/qwen3coder_verified_minisweagent/output.jsonl"):
    for l in open(f):
        d = json.loads(l); done[d["instance_id"]] = d["exit_status"]
ohrows = {r["iid"]: r for r in json.load(open(f"{E}/analysis/qwen3coder_verified_tasks.json"))}
ids = [i for i in done if i in msa and i in oh and done[i] in ("Submitted", "LimitsExceeded")]
print(f"{len(ids)} tasks finished by mini-SWE-agent (Submitted or step cap) with OpenHands data; "
      f"msa exits {dict(collections.Counter(done[i] for i in ids))}; OpenHands own stop "
      f"{sum(bool(ohrows[i]['finished']) for i in ids if i in ohrows)}/{len(ids)}")
M = {"steps (model calls)": lambda a: a["calls"], "prompt tokens (k)": lambda a: a["p"] / 1e3,
     "completion tokens (k)": lambda a: a["o"] / 1e3, "completion per step": lambda a: a["o"] / max(a["calls"], 1),
     "uncached compute tokens (k)": lambda a: (a["p"] - a["c"] + a["o"]) / 1e3,
     "context at last step (k tokens)": lambda a: a["last_p"] / 1e3, "wall time (min)": lambda a: (a["t1"] - a["t0"]) / 60}
print(f"{'per task':34s} {'OpenHands median/mean':>22s} {'mini-SWE median/mean':>22s}  {'ratio msa/OH (median)':>21s}")
for k, f in M.items():
    o = [f(oh[i]) for i in ids]; m = [f(msa[i]) for i in ids]; r = [b / a for a, b in zip(o, m) if a]
    print(f"{k:34s} {st.median(o):10.1f} / {st.mean(o):8.1f}  {st.median(m):10.1f} / {st.mean(m):8.1f}  {st.median(r):17.2f}")
tot = lambda d, f: sum(f(d[i]) for i in ids)
print(f"totals over these tasks: steps OH {tot(oh, M['steps (model calls)']):.0f} vs msa {tot(msa, M['steps (model calls)']):.0f}; "
      f"uncached compute OH {tot(oh, M['uncached compute tokens (k)'])/1e3:.1f}M vs msa {tot(msa, M['uncached compute tokens (k)'])/1e3:.1f}M; "
      f"prompt tokens OH {tot(oh, M['prompt tokens (k)'])/1e3:.0f}M vs msa {tot(msa, M['prompt tokens (k)'])/1e3:.0f}M")
fewer = sum(msa[i]["calls"] < oh[i]["calls"] for i in ids)
print(f"mini-SWE-agent uses fewer steps on {fewer}/{len(ids)} tasks")
