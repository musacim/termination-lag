#!/usr/bin/env python3
"""Replace tasks of a run with their rerun.
usage: tl_merge.py <base> <rerun> <out>"""
import os
import json, sys
A = os.path.join(os.environ.get("TL_ROOT", "."), "analysis")
b, r, o = sys.argv[1:4]
new = {x["iid"]: x for x in json.load(open(f"{A}/{r}_tasks.json"))}
rows = [new.get(x["iid"], x) for x in json.load(open(f"{A}/{b}_tasks.json"))]
json.dump(rows, open(f"{A}/{o}_tasks.json", "w"))
print(f"wrote {A}/{o}_tasks.json: {len(rows)} tasks, {sum(x['iid'] in new for x in rows)} from {r} (rerun has {len(new)})")
