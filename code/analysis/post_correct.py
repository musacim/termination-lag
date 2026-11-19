#!/usr/bin/env python3
"""Actions after the first correct patch, by kind, and what happens to the patch afterwards.
usage: post_correct.py <run>:<run dir>[,<run dir>...]"""
import collections, glob, json, os, re, statistics as st, sys
A = os.path.join(os.environ.get("TL_ROOT", "."), "analysis"); E = os.path.dirname(A)

SCRIPT = re.compile(r"(^|/)(reproduce|repro|debug|verify|verification|check|demo|example|simple|final|edge|comprehensive|"
                    r"minimal|quick|manual|my_|tmp|temp|scratch|analy[sz]e|investigate|trace|explore|issue)[^/]*\.(py|sh|js|ts|go|rs|rb|php|c|java)$|"
                    r"(^|/)test_[^/]*\.(py|js|ts|go|rs|rb|php|java)$")
REPO_TEST = re.compile(r"/(tests?|testing|spec|__tests__)/")
TEST_RUN = re.compile(r"\b(pytest|py\.test|runtests\.py|bin/test|tox\b|unittest|nosetests|go test|cargo test|npm (run )?test|"
                      r"yarn (run )?test|jest|mocha|phpunit|rspec|bundle exec|mvn |gradle|ctest|make (check|test))")
SEARCH = re.compile(r"^\s*(cd [^&;]+(&&|;)\s*)?(grep|rg|find|ls|cat|head|tail|sed -n|wc|tree|less|more|awk|file|stat)\b")


def classify(a, created):
    k = a.get("kind")
    if k == "FinishAction":
        return "finish"
    if k == "ThinkAction":
        return "think"
    if k == "FileEditorAction":
        cmd, p = a.get("command"), a.get("path") or ""
        own = p in created or bool(SCRIPT.search(p))
        if cmd == "view":
            return "view own script" if own else "view code"
        if cmd == "create":
            created.add(p)
            return "write test/repro script" if (own or REPO_TEST.search(p)) else "create source file"
        if REPO_TEST.search(p) and not own:
            return "edit repo tests"
        return "edit own script" if own else "edit source"
    if k == "TerminalAction":
        c = a.get("command") or ""
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
    return "other (" + str(k) + ")"


GROUP = {"run repo tests": "verify", "run own script": "verify", "build": "verify", "write test/repro script": "verify",
         "edit own script": "verify", "view own script": "verify",
         "view code": "explore", "search/inspect": "explore", "git": "explore",
         "edit source": "re-edit source", "create source file": "re-edit source", "edit repo tests": "edit repo tests",
         "cleanup (rm)": "wrap-up", "finish": "wrap-up", "think": "think", "install": "other", "other shell": "other"}


def load_traj(globs):
    out = {}
    for g in globs:
        part = {}
        for f in glob.glob(f"{E}/{g}/trajectories/output*.jsonl"):
            if "critic" in f:
                continue
            for l in open(f):
                try:
                    d = json.loads(l)
                except Exception:
                    continue
                h = d.get("history") or []
                if not h:
                    continue
                steps, idx = [], {}
                ex = {e.get("action_id"): (e.get("observation") or {}).get("exit_code") for e in h if e.get("kind") == "ObservationEvent"}
                for e in h:
                    if e.get("kind") != "ActionEvent":
                        continue
                    rid = e.get("llm_response_id") or e.get("id")
                    if rid not in idx:
                        idx[rid] = len(steps); steps.append([])
                    steps[idx[rid]].append(dict(e.get("action") or {}, _exit=ex.get(e.get("id"))))
                if len(steps) >= len(part.get(d["instance_id"], [])):
                    part[d["instance_id"]] = steps
        out.update(part)
    return out


def main(tag, globs):
    rows = {r["iid"]: r for r in json.load(open(f"{A}/{tag}_tasks.json"))}
    traj = load_traj(globs)
    cats, groups = collections.Counter(), collections.Counter()
    per_task, patch = [], collections.Counter()
    for iid, r in rows.items():
        fc = r.get("first_correct")
        if not (r.get("final") and fc and iid in traj):
            continue
        steps = traj[iid]
        if fc >= len(steps) + 1:
            continue
        created = set()
        pre = [classify(a, created) for s in steps[:fc] for a in s]
        post_a = [a for s in steps[fc:] for a in s]
        post = [classify(a, created) for a in post_a]
        runs = [(c, a) for c, a in zip(post, post_a) if c in ("run repo tests", "run own script", "build")]
        ok = [a.get("_exit") == 0 for c, a in runs if a.get("_exit") is not None]
        norm = [re.sub(r"\s+", " ", a.get("command") or "").strip() for c, a in runs]
        rerun = sum(1 for i, x in enumerate(norm) if x in norm[:i])
        newscripts = sum(c == "write test/repro script" for c in post)
        if not post:
            continue
        cats.update(post); g = collections.Counter(GROUP.get(c, "other") for c in post); groups.update(g)
        ms = {int(k): v for k, v in r["ms"].items()}
        later = [ms[k] for k in sorted(ms) if k > fc and ms[k] is not None]
        flips = sum(1 for a, b in zip([True] + later, later) if a != b)
        patch["stays correct" if all(later) else "goes wrong, then correct again" if later and later[-1] else "goes wrong"] += 1
        per_task.append({"iid": iid, "fc": fc, "stop": r["stop"], "finished": r["finished"], "post": len(post),
                         "groups": dict(g), "flips": flips, "src_edits": sum(c in ("edit source", "create source file") for c in post),
                         "first_post": post[:5], "runs": len(runs), "runs_ok": sum(ok), "runs_known": len(ok),
                         "reruns": rerun, "new_scripts": newscripts})
    n = len(per_task); tot = sum(cats.values())
    print(f"== {tag}: {n} solved tasks with a trajectory; {tot} actions after the first correct patch")
    print("  by group (share of all post-correct actions):")
    for k, v in groups.most_common():
        sh = [t["groups"].get(k, 0) / t["post"] for t in per_task]
        print(f"    {k:18s} {100*v/tot:5.1f}%   per task median share {100*st.median(sh):4.0f}%")
    print("  by action:")
    for k, v in cats.most_common(12):
        print(f"    {k:26s} {100*v/tot:5.1f}%")
    se = [t["src_edits"] for t in per_task]
    print(f"  tasks that edit source again after the fix: {sum(x > 0 for x in se)} ({100*sum(x > 0 for x in se)/n:.0f}%), median edits among them "
          f"{st.median([x for x in se if x] or [0])}")
    print("  patch after the first correct step:", {k: f"{v} ({100*v/n:.0f}%)" for k, v in patch.items()})
    R = sum(t["runs"] for t in per_task); K = sum(t["runs_known"] for t in per_task); O = sum(t["runs_ok"] for t in per_task)
    print(f"  verification runs after the fix (tests, own scripts, builds): median {st.median([t['runs'] for t in per_task])} per task; "
          f"{100*O/max(K,1):.0f}% exit 0; {100*sum(t['reruns'] for t in per_task)/max(R,1):.0f}% repeat an earlier post-fix command; "
          f"new test/repro scripts written after the fix: median {st.median([t['new_scripts'] for t in per_task])}")
    fp = collections.Counter(GROUP.get(t["first_post"][0], "other") for t in per_task)
    print("  first action after the fix:", dict(fp.most_common()))
    json.dump({"tag": tag, "tasks": per_task, "actions": dict(cats), "groups": dict(groups), "patch": dict(patch)},
              open(f"{A}/{tag}_postcorrect.json", "w"))


if __name__ == "__main__":
    for spec in sys.argv[1:]:
        tag, gl = spec.split(":", 1)
        main(tag, gl.split(","))
