#!/usr/bin/env python3
"""Map the proxy's logged model calls to SWE-bench task ids.
usage: map_steps.py <run_dir>"""
import os
import json, sys
import pyarrow.parquet as pq

REP = sys.argv[1]
DS = (os.environ.get("HF_HUB_DIR", "hf_hub") + "/datasets--princeton-nlp--SWE-bench_Verified/snapshots/"
      "c104f840cc67f8b6eec6f759ebc8b2693d585d4a/data/test-00000-of-00001.parquet")
ids = {l.strip() for l in open(f"{REP}/instances.txt") if l.strip()}
t = pq.read_table(DS, columns=["instance_id", "problem_statement"]).to_pylist()
keys = {r["instance_id"]: " ".join(r["problem_statement"].split())[:300] for r in t if r["instance_id"] in ids}

steps = [json.loads(l) for l in open(f"{REP}/steps.jsonl")]
conv2iid = {}
for s in steps:
    if "head" in s and s["conv"] not in conv2iid:
        h = " ".join(s["head"].split())
        hit = [i for i, k in keys.items() if k and k in h]
        conv2iid[s["conv"]] = hit[0] if len(hit) == 1 else None
import collections
ncalls = collections.Counter(s["conv"] for s in steps)
agent_conv = {}
for c, i in conv2iid.items():
    if i and (i not in agent_conv or ncalls[c] > ncalls[agent_conv[i]]):
        agent_conv[i] = c
agent_set = set(agent_conv.values())
with open(f"{REP}/steps_mapped.jsonl", "w") as w:
    for s in steps:
        s.pop("head", None)
        s["instance_id"] = conv2iid.get(s["conv"])
        s["agent"] = s["conv"] in agent_set
        w.write(json.dumps(s) + "\n")
mapped = {c: i for c, i in conv2iid.items() if i}
print(f"{REP}: {len(steps)} calls, {len(conv2iid)} conversations, {len(mapped)} mapped to tasks "
      f"({len(set(mapped.values()))} distinct of {len(ids)}), "
      f"{sum(1 for s in steps if s['agent'])} agent calls, {sum(1 for s in steps if not s['agent'])} helper/unmapped calls")
