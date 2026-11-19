#!/usr/bin/env python3
"""Collect every per-step patch and final patch of one run, deduplicated per task, into grading batches.
usage: build_ml_preds.py <run>   (reads runs/<run>*/, writes analysis/grading_<run>/; ONLY_TASKS=<file> limits the tasks)"""
import collections, glob, hashlib, json, os, re, sys
ES = os.environ.get("TL_ROOT", "."); PX = sys.argv[1]
OUT = f"{ES}/analysis/grading_{PX}"
H = lambda p: hashlib.sha1(p.encode()).hexdigest()[:16]
MODEL = os.environ.get("MODEL_NAME", PX)
ONLY = set(open(os.environ["ONLY_TASKS"]).read().split()) if os.environ.get("ONLY_TASKS") else None
patches = collections.defaultdict(dict)
index = []
for arm in (PX,):
    for rep in ("01",):
        for d in sorted(glob.glob(f"{ES}/runs/{PX}*/")):
            d = d.rstrip("/")
            rows = {}
            for f in ("output_errors.partial.jsonl", "output.partial.jsonl", "output_errors.jsonl", "output.jsonl"):
                p = f"{d}/trajectories/{f}"
                if os.path.exists(p):
                    for l in open(p):
                        if not l.endswith("}\n"):
                            continue
                        x = json.loads(l); rows[x["instance_id"]] = (x.get("test_result") or {}).get("git_patch") or ""
            if not os.path.exists(f"{d}/instances.txt"):
                continue
            for iid in (l.strip() for l in open(f"{d}/instances.txt") if l.strip()):
                if ONLY is not None and iid not in ONLY:
                    continue
                md = f"{d}/milestones/{iid}"
                ms = sorted(glob.glob(f"{md}/step*.diff"))
                for m in ms:
                    p = open(m, errors="ignore").read(); h = H(p); patches[iid][h] = p
                    index.append(dict(arm=arm, rep=rep, iid=iid, kind="milestone", step=int(re.search(r"step(\d+)", m).group(1)), h=h))
                if iid in rows:
                    p, st, src = rows[iid], None, "agent"
                else:
                    p = open(ms[-1], errors="ignore").read() if ms else ""; st = int(re.search(r"step(\d+)", ms[-1]).group(1)) if ms else None
                    src = "straggler"
                h = H(p); patches[iid][h] = p
                index.append(dict(arm=arm, rep=rep, iid=iid, kind="final", step=st, src=src, h=h))
import shutil
shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
EMPTY = H("")
batch_of, nb = {}, 0
for iid, hs in patches.items():
    for k, (h, p) in enumerate(sorted((h, p) for h, p in hs.items() if p.strip())):
        bd = f"{OUT}/batch_{k:02d}"; os.makedirs(bd, exist_ok=True); nb = max(nb, k + 1)
        with open(f"{bd}/predictions.jsonl", "a") as w:
            w.write(json.dumps({"instance_id": iid, "model_name_or_path": f"{MODEL}-{PX}-{h}", "model_patch": p}) + "\n")
        batch_of[f"{iid}|{h}"] = k
json.dump(dict(index=index, batch_of=batch_of), open(f"{OUT}/index.json", "w"))
n = sum(sum(1 for p in v.values() if p.strip()) for v in patches.values())
print(f"{len(index)} (arm,rep,task,kind,step) entries -> {n} unique patches in {nb} batches "
      f"(sizes {[sum(1 for l in open(f'{OUT}/batch_{k:02d}/predictions.jsonl')) for k in range(nb)]})")
print("final sources:", collections.Counter((e['arm'], e['src']) for e in index if e['kind'] == 'final'))
