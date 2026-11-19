#!/usr/bin/env python3
"""First patch (first step that edits a non-test source file) and attempts until the first correct patch.
usage: first_patch.py"""
import glob, json, os, re, statistics as st
TESTP = re.compile(r"(^|/)(tests?|testing|spec|__tests__|test_?data|fixtures)/|(^|/)test_[^/]*$|_test\.[a-z]+$|"
                   r"[._-](test|spec)\.[a-z]+$|Tests?\.java$")


def src_part(d):
    keep = []
    for b in re.split(r"(?m)^(?=diff --git )", d or ""):
        m = re.match(r"diff --git a/(\S+) b/(\S+)", b)
        if m and "\nnew file mode" not in b.split("\n@@")[0] and not TESTP.search(m.group(2)) and "\n@@" in b:
            keep.append(b)
    return "".join(sorted(keep))
E = os.environ.get("TL_ROOT", "."); A = f"{E}/analysis"
SETS = [("Qwen Verified", "qwen3coder_verified", ["runs/qwen3coder_verified"]), ("Qwen Multi.", "qwen3coder_multilingual", ["runs/qwen3coder_multilingual"]),
        ("Laguna Verified", "laguna_verified", ["runs/laguna_verified_100step", "runs/laguna_verified_250step", "runs/laguna_verified_256k"]),
        ("Laguna Multi.", "laguna_multilingual", ["runs/laguna_multilingual_100step", "runs/laguna_multilingual_250step", "runs/laguna_multilingual_256k"]),
        ("Seed-OSS Pro", "seedoss_pro300", ["runs/seedoss_pro300"]),
        ("mini-SWE-agent Qwen Verified", "qwen3coder_verified_minisweagent", ["runs/qwen3coder_verified_minisweagent"])]
out = {}
for name, tag, globs in SETS:
    md = {}
    for g in globs:
        for d in glob.glob(f"{E}/{g}/milestones/*"):
            if glob.glob(f"{d}/step*.diff"):
                md[os.path.basename(d)] = d
    res = []
    for r in json.load(open(f"{A}/{tag}_tasks.json")):
        fc = r["first_correct"]
        if not fc or r["iid"] not in md:
            continue
        prev, fp, att = None, None, 0
        for k in range(1, fc + 1):
            f = f"{md[r['iid']]}/step{k:03d}.diff"
            sp = src_part(open(f, errors="replace").read()) if os.path.exists(f) else prev
            if sp and sp != prev:
                att += 1
                fp = fp or k
            prev = sp if sp is not None else prev
        if fp is None:
            fp, att = fc, 1
        res.append({"iid": r["iid"], "first_patch": fp, "first_correct": fc, "attempts": att,
                    "first_ok": bool(r["ms"].get(str(fp)))})
    out[tag] = res
    n = len(res)
    print(f"{name:28s} runs {n:3d} | first patch step median {st.median(x['first_patch'] for x in res):5.1f} | "
          f"first correct step median {st.median(x['first_correct'] for x in res):5.1f} | "
          f"first patch already correct {100*sum(x['first_ok'] for x in res)/n:3.0f}% | "
          f"attempts to the first correct patch mean {st.mean(x['attempts'] for x in res):4.1f}, "
          f"median {st.median(x['attempts'] for x in res):3.1f}")
json.dump(out, open(f"{A}/first_patch.json", "w"))
