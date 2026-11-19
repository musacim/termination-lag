#!/usr/bin/env python3
"""Context growth from the first correct step to the end of each solved run.
usage: ctx_growth.py [--all]"""
import os
import collections, glob, json, statistics as st, sys
E = os.environ.get("TL_ROOT", "."); A = f"{E}/analysis"
COLS = [("Qwen V", "qwen3coder_verified", "swebench_verified_meta", ["runs/qwen3coder_verified"], []),
        ("Qwen ML", "qwen3coder_multilingual", "swebench_multilingual_meta", ["runs/qwen3coder_multilingual"], []),
        ("Lag V", "laguna_verified", "swebench_verified_meta",
         ["runs/laguna_verified_100step", "runs/laguna_verified_250step", "runs/laguna_verified_256k"], ["laguna_verified_250step", "laguna_verified_256k"]),
        ("Lag ML", "laguna_multilingual", "swebench_multilingual_meta",
         ["runs/laguna_multilingual_100step", "runs/laguna_multilingual_250step", "runs/laguna_multilingual_256k"], ["laguna_multilingual_250step", "laguna_multilingual_256k"])]


def step_tokens(g, meta):
    keys = {i: m["key"] for i, m in json.load(open(f"{E}/tasks/{meta}.json")).items()}
    out = collections.defaultdict(dict)
    for f in glob.glob(f"{E}/{g}/steps.jsonl"):
        conv, title, recs = {}, set(), []
        for l in open(f):
            d = json.loads(l)
            if d.get("async"):
                continue
            if "head" in d:
                h = " ".join(d["head"].split()); hit = [i for i, k in keys.items() if k in h]
                if len(hit) == 1:
                    conv[d["conv"]] = hit[0]
                if d["head"].startswith("Generate a title"):
                    title.add(d["conv"])
            recs.append(d)
        for d in recs:
            iid = conv.get(d["conv"])
            if iid and "prompt_tokens" in d and d["conv"] not in title:
                out[iid][d["step"]] = (d.get("prompt_tokens") or 0, d.get("completion_tokens") or 0)
    return out


print(f"{'col':8s} {'n':>4s} {'ctx F':>7s} {'ctx end':>8s} {'growth med':>10s} {'p90':>6s} {'missing':>7s}")
for name, tag, meta, globs, lists in COLS:
    tok = {}
    for i, g in enumerate(globs):
        keep = None if i == 0 else {l.split()[0] for l in open(f"{E}/tasks/{lists[i - 1]}.txt") if l.strip()}
        tok.update({k: v for k, v in step_tokens(g, meta).items() if keep is None or k in keep})
    pc = {t["iid"] for t in json.load(open(f"{A}/{tag}_postcorrect.json"))["tasks"]}
    cf, ce, gr, miss = [], [], [], 0
    for r in json.load(open(f"{A}/{tag}_tasks.json")):
        F = r["first_correct"]
        if ("--all" not in sys.argv and r["iid"] not in pc) or F is None or not r["final"]:
            continue
        s = tok.get(r["iid"])
        if not s or F not in s:
            miss += 1; continue
        f, e = s[F][0], sum(s[max(s)])
        cf.append(f); ce.append(e); gr.append((e - f) / f)
    print(f"{name:8s} {len(gr):4d} {st.median(cf):7.0f} {st.median(ce):8.0f} {100 * st.median(gr):9.0f}% "
          f"{100 * st.quantiles(gr, n=10)[-1]:5.0f}% {miss:7d}")
