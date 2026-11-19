#!/usr/bin/env python3
"""Reproduce the termination-lag table from results/per_task.
usage: python scripts/reproduce_table.py [results/per_task]"""
import json, os, statistics, sys

RUNS = [
    ("qwen3coder_verified", "Qwen3-Coder-30B-A3B", "SWE-bench Verified"),
    ("qwen3coder_multilingual", "Qwen3-Coder-30B-A3B", "SWE-bench Multilingual"),
    ("laguna_verified", "Laguna-XS.2", "SWE-bench Verified"),
    ("laguna_multilingual", "Laguna-XS.2", "SWE-bench Multilingual"),
    ("seedoss_pro300", "Seed-OSS-36B", "SWE-bench Pro (300 tasks)"),
    ("qwen3coder_verified_minisweagent", "Qwen3-Coder-30B-A3B, mini-SWE-agent", "SWE-bench Verified"),
]


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "per_task")
    print(f"{'model':36s} {'benchmark':31s} {'tasks':>5s} {'solved%':>7s} {'TTFCP':>6s} {'S':>5s} {'TL':>5s} {'NTL%':>5s}")
    for tag, model, bench in RUNS:
        p = os.path.join(d, f"{tag}.json")
        if not os.path.exists(p):
            continue
        tasks = json.load(open(p))
        sol = [t for t in tasks if t["final"] and t["first_correct"] is not None]
        med = lambda xs: statistics.median(xs)
        F = med([t["first_correct"] for t in sol]); S = med([t["stop"] for t in sol])
        TL = med([t["stop"] - t["first_correct"] for t in sol])
        NTL = med([(t["stop"] - t["first_correct"]) / t["stop"] for t in sol]) * 100
        print(f"{model:36s} {bench:31s} {len(tasks):5d} {100 * len(sol) / len(tasks):7.1f} {F:6g} {S:5g} {TL:5g} {NTL:5.0f}")


if __name__ == "__main__":
    main()
