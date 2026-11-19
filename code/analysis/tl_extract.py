#!/usr/bin/env python3
"""Per task: grade of every step's patch, first edit, first correct step, stop step and final result.
usage: tl_extract.py <grading,...> <run dir> <task meta json> <run>"""
import os
import collections, glob, json, sys
PXS, RUNS, META, TAG = sys.argv[1].split(","), sys.argv[2], sys.argv[3], sys.argv[4]
E = os.environ.get("TL_ROOT", "."); A = f"{E}/analysis"
meta = json.load(open(f"{E}/{META}"))
ms = collections.defaultdict(dict); fin = {}; missing = []
for px in PXS:
    G = f"{A}/grading_{px}"; I = json.load(open(f"{G}/index.json")); bo = I["batch_of"]; cache = {}
    def res(iid, h):
        k = f"{iid}|{h}"
        if k not in bo: return None
        if k not in cache:
            try: cache[k] = bool(json.load(open(f"{G}/batch_{bo[k]:02d}/res/run/{iid}/report.json")).get(iid, {}).get("resolved"))
            except FileNotFoundError: cache[k] = False; missing.append(k)
        return cache[k]
    for e in I["index"]:
        r = res(e["iid"], e["h"])
        if e["kind"] == "milestone": ms[e["iid"]][e["step"]] = r
        else: fin[e["iid"]] = bool(r)
finished = set()
for f in glob.glob(f"{E}/{RUNS}/trajectories/output.jsonl") + glob.glob(f"{E}/{RUNS}/trajectories/output.partial.jsonl"):
    for l in open(f):
        try: d = json.loads(l)
        except Exception: continue
        if not d.get("error"): finished.add(d["instance_id"])
conv = collections.defaultdict(int); task_of = {}
for f in glob.glob(f"{E}/{RUNS}/steps.jsonl"):
    for l in open(f):
        d = json.loads(l); c = d["conv"]; conv[c] = max(conv[c], d["step"] + 1)
        if "head" in d and not d["head"].startswith("Generate a title"):
            h = " ".join(d["head"].split()); hit = [i for i, m in meta.items() if m["key"] in h]
            if len(hit) == 1: task_of[c] = hit[0]
nsteps = {}
for c, iid in task_of.items(): nsteps[iid] = max(nsteps.get(iid, 0), conv[c])
mdir = {d.rstrip("/").split("/")[-1]: d for d in glob.glob(f"{E}/{RUNS}/milestones/*/")}
def content(path):
    try: t = open(path, errors="ignore").read()
    except FileNotFoundError: return None
    return tuple(sorted(b for b in t.split("diff --git ")[1:]
                        if any(l.startswith(("@@", "Binary files", "new file mode", "deleted file mode", "rename "))
                               for l in b.splitlines())))
def first_edit(iid, upto):
    d = mdir.get(iid); base = content(f"{d}step001.diff") if d else None
    if base is None or not upto: return None
    for k in range(2, upto + 1):
        c = content(f"{d}step{k:03d}.diff")
        if c is not None and c != base: return k
    return None
out = []
for iid in sorted(fin):
    m = ms[iid]; fc = min((s for s, r in m.items() if r), default=None); n = nsteps.get(iid)
    out.append(dict(iid=iid, ms={str(k): v for k, v in sorted(m.items())}, first_correct=fc,
                    first_edit=first_edit(iid, n), stop=n, finished=iid in finished, final=fin[iid]))
json.dump(out, open(f"{A}/{TAG}_tasks.json", "w"))
print(f"wrote {A}/{TAG}_tasks.json: {len(out)} tasks; {len(missing)} patches without a grade counted unresolved")
