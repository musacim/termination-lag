#!/usr/bin/env python3
"""Reproduce the paper's tables from the Hugging Face dataset musacim/termination-lag-trajectories.
usage: python scripts/from_hf.py [--data DIR] [--ctx]   (needs huggingface_hub, pyarrow; tokenizers for --ctx)"""
import argparse, collections, json, os, re, statistics as st

REPO = "musacim/termination-lag-trajectories"
RUNS = ["qwen3coder_verified", "qwen3coder_multilingual", "laguna_verified", "laguna_multilingual", "seedoss_pro300",
        "qwen3coder_verified_minisweagent"]
TOKENIZER = {"Qwen3-Coder-30B-A3B": "Qwen/Qwen3-Coder-30B-A3B-Instruct", "Laguna-XS.2": "poolside/Laguna-XS.2"}

TESTP = re.compile(r"(^|/)(tests?|testing|spec|__tests__|test_?data|fixtures)/|(^|/)test_[^/]*$|_test\.[a-z]+$|"
                   r"[._-](test|spec)\.[a-z]+$|Tests?\.java$")


def src_part(d):
    if d is None:
        return None
    keep = []
    for b in re.split(r"(?m)^(?=diff --git )", d):
        m = re.match(r"diff --git a/(\S+) b/(\S+)", b)
        if m and "\nnew file mode" not in b.split("\n@@")[0] and not TESTP.search(m.group(2)) and "\n@@" in b:
            keep.append(b)
    return "".join(sorted(keep))


SCRIPT = re.compile(r"(^|/)(reproduce|repro|debug|verify|verification|check|demo|example|simple|final|edge|comprehensive|"
                    r"minimal|quick|manual|my_|tmp|temp|scratch|analy[sz]e|investigate|trace|explore|issue)[^/]*\."
                    r"(py|sh|js|ts|go|rs|rb|php|c|java)$|(^|/)test_[^/]*\.(py|js|ts|go|rs|rb|php|java)$")
REPO_TEST = re.compile(r"/(tests?|testing|spec|__tests__)/")
TEST_RUN = re.compile(r"\b(pytest|py\.test|runtests\.py|bin/test|tox\b|unittest|nosetests|go test|cargo test|npm (run )?test|"
                      r"yarn (run )?test|jest|mocha|phpunit|rspec|bundle exec|mvn |gradle|ctest|make (check|test))")
SEARCH = re.compile(r"^\s*(cd [^&;]+(&&|;)\s*)?(grep|rg|find|ls|cat|head|tail|sed -n|wc|tree|less|more|awk|file|stat)\b")
GROUP = {"run repo tests": "Verify", "run own script": "Verify", "build": "Verify", "write test/repro script": "Verify",
         "edit own script": "Verify", "view own script": "Verify",
         "view code": "Explore", "search/inspect": "Explore", "git": "Explore",
         "edit source": "Edit the source again", "create source file": "Edit the source again",
         "cleanup (rm)": "Wrap-up", "finish": "Wrap-up"}
GROUPS = ["Verify", "Explore", "Edit the source again", "Wrap-up", "Think, other"]


def classify(tool, args, created):
    if tool == "finish":
        return "finish"
    if tool == "think":
        return "think"
    if tool == "file_editor":
        cmd, p = args.get("command"), args.get("path") or ""
        own = p in created or bool(SCRIPT.search(p))
        if cmd == "view":
            return "view own script" if own else "view code"
        if cmd == "create":
            created.add(p)
            return "write test/repro script" if (own or REPO_TEST.search(p)) else "create source file"
        if REPO_TEST.search(p) and not own:
            return "edit repo tests"
        return "edit own script" if own else "edit source"
    if tool in ("terminal", "bash"):
        c = args.get("command") or ""
        if re.search(r"(^|[;&|]\s*)rm\s", c) and not TEST_RUN.search(c) and "python" not in c:
            return "cleanup (rm)"
        if TEST_RUN.search(c):
            return "run repo tests"
        if re.search(r"\b(cargo build|go build|go vet|make\b|cmake|javac|mvn (compile|package)|gradle|npm run build|yarn build|"
                     r"gcc|g\+\+|clang|tsc\b|composer (install|dump))", c):
            return "build"
        if re.search(r"\bpython[0-9.]*\s+(-c|-m\s+(?!pytest)|\S+\.py|-\s*(<<|$))|\bnode\s|\bgo run\b|\bcargo run\b|\bruby\s|\bphp\s|"
                     r"\bjava\s|\bnpx\s|(^|[;&]\s*)\./\S+|\bbash\s+\S+\.sh", c):
            return "run own script"
        if re.search(r"\bgit\s+(-C\s+\S+\s+|--no-pager\s+)*(diff|status|log|show|stash|checkout|restore|reset)", c):
            return "git"
        if re.search(r"\b(pip|conda|npm|yarn|apt|cargo)\s+(install|add)", c):
            return "install"
        if SEARCH.search(c):
            return "search/inspect"
        return "other shell"
    return "other"


def calls(step):
    out = []
    for tc in step.get("tool_calls") or []:
        a = tc.get("arguments")
        try:
            a = json.loads(a) if isinstance(a, str) else (a or {})
        except ValueError:
            a = {}
        out.append((tc.get("tool"), a if isinstance(a, dict) else {}))
    return out


def load(data, run, kind):
    import pyarrow.parquet as pq
    if data:
        path = os.path.join(data, "data", run, f"{kind}.parquet")
    else:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(REPO, f"data/{run}/{kind}.parquet", repo_type="dataset")
    return pq.read_table(path).to_pylist()


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data")
    ap.add_argument("--ctx", action="store_true")
    o = ap.parse_args()
    tok = {}
    for run in RUNS:
        T, P = load(o.data, run, "trajectories"), load(o.data, run, "patches")
        patch = {(p["instance_id"], p["patch_id"]): p for p in P}
        ok = lambda t, i: bool(i) and patch[(t["instance_id"], i)]["resolved"]
        sol = [t for t in T if t["resolved"] and t["first_correct"] is not None]
        reach = [t for t in T if t["first_correct"] is not None]
        print(f"\n== {run}: {T[0]['model']}, {T[0]['benchmark']}, {T[0]['framework']}, {len(T)} tasks")

        F = [t["first_correct"] for t in sol]; S = [t["stop"] for t in sol]
        print(f"  Table 1  solved {100 * len(sol) / len(T):.1f}% | TTFCP {st.median(F):g} | S {st.median(S):g} | "
              f"TL {st.median([s - f for s, f in zip(S, F)]):g} | NTL {100 * st.median([(s - f) / s for s, f in zip(S, F)]):.0f}%")

        fp_steps, fp_ok, att = [], 0, []
        for t in reach:
            prev, fp, n = None, None, 0
            for k in range(1, t["first_correct"] + 1):
                i = t["step_patch_ids"][k - 1]
                sp = src_part(patch[(t["instance_id"], i)]["patch"]) if i else ""
                if sp and sp != prev:
                    n += 1; fp = fp or k
                prev = sp
            if fp is None:
                fp, n = t["first_correct"], 1
            fp_steps.append(fp); att.append(n); fp_ok += ok(t, t["step_patch_ids"][fp - 1])
        print(f"  Table 2  first patch step {st.median(fp_steps):g} | first correct step "
              f"{st.median([t['first_correct'] for t in reach]):g} | first patch already correct {pct(fp_ok, len(reach))} | "
              f"attempts until correct {st.mean(att):.1f}   ({len(reach)} runs reach a correct patch)")

        out = collections.Counter()
        for t in reach:
            later = [ok(t, i) for i in t["step_patch_ids"][t["first_correct"]:] if i]
            out["broken" if not t["resolved"] else "stays" if all(later) else "fixed"] += 1
        print(f"  Table 3  patch after the fix: stays correct {pct(out['stays'], len(reach))} | breaks, correct again "
              f"{pct(out['fixed'], len(reach))} | breaks, run ends unsolved {pct(out['broken'], len(reach))}")

        g, n = collections.Counter(), 0
        for t in sol if T[0]["framework"] == "OpenHands" else []:
            if not (t["trajectory"] and t["trajectory_complete"]):
                continue
            steps = json.loads(t["trajectory"]); fc = t["first_correct"]
            if fc >= len(steps) + 1:
                continue
            created = set()
            for s in steps[:fc]:
                for tool, a in calls(s):
                    classify(tool, a, created)
            post = [GROUP.get(classify(tool, a, created), "Think, other") for s in steps[fc:] for tool, a in calls(s)]
            if post:
                g.update(post); n += 1
        tot = sum(g.values())
        if tot: print("  Table 3  steps after the fix: " + " | ".join(f"{k} {pct(g[k], tot)}" for k in GROUPS) + f"   ({n} runs)")

        if o.ctx and T[0]["model"] in TOKENIZER and T[0]["framework"] == "OpenHands":
            from huggingface_hub import hf_hub_download
            from tokenizers import Tokenizer
            m = T[0]["model"]
            if m not in tok:
                tok[m] = Tokenizer.from_file(hf_hub_download(TOKENIZER[m], "tokenizer.json"))
            ntok = lambda x: len(tok[m].encode(x if isinstance(x, str) else json.dumps(x), add_special_tokens=False).ids)
            tp = {t["instance_id"]: ntok(t["task_prompt"] or "") for t in T}
            base = 8300 - st.median(tp.values())
            gr = []
            for t in sol:
                if not (t["trajectory"] and t["trajectory_complete"]):
                    continue
                per = [ntok(s.get("message") or "") + ntok(s.get("tool_calls") or "") + ntok(s.get("observations") or "")
                       for s in json.loads(t["trajectory"])]
                cf = base + tp[t["instance_id"]] + sum(per[:t["first_correct"]])
                gr.append((base + tp[t["instance_id"]] + sum(per) - cf) / cf)
            print(f"  Context growth (estimate): median +{100 * st.median(gr):.0f}%, mean +{100 * st.mean(gr):.0f}%   ({len(gr)} runs)")


if __name__ == "__main__":
    main()
