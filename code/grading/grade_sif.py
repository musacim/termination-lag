#!/usr/bin/env python3
"""Grade SWE-bench predictions inside the task containers with the official SWE-bench evaluation.
usage: grade_sif.py --predictions F --dataset F --sif-dir D --run-id ID --out D"""
import argparse, concurrent.futures as cf, fcntl, glob, json, os, shutil, socket, subprocess, time
socket.setdefaulttimeout(120)
from swebench.harness.test_spec.test_spec import make_test_spec
from swebench.harness.grading import get_eval_report
from swebench.harness.constants import APPLY_PATCH_FAIL, APPLY_PATCH_PASS, TESTS_TIMEOUT

APPLY = ["git apply --verbose", "git apply --verbose --reject", "patch --batch --fuzz=5 -p1 -i"]
PX = os.environ.get("SWEB_CONTAINER_PROXY", "")
PORT_GROUP = {"valkey-io/valkey": "redis/redis"}
FIXED_PORTS = {"axios/axios", "redis/redis", "valkey-io/valkey", "caddyserver/caddy", "fluent/fluentd"}
NETNS = os.environ.get("GRADE_NETNS") == "1"

def rmtree_force(d):
    if os.path.exists(d):
        subprocess.run(f"chmod -R u+w '{d}' 2>/dev/null; rm -rf '{d}'", shell=True)


def find_sif(sif_dir, iid):
    repo, name = iid.split("__", 1)
    hits = [p for p in glob.glob(f"{sif_dir}/*sweb.eval.x86_64.{repo}_1776_{name}-*.sif") if not p.endswith(".tmp.sif")]
    return hits[0] if hits else None

def grade_one(pred, inst, a):
    iid = pred["instance_id"]
    wd = os.path.join(a.out, a.run_id, iid); os.makedirs(wd, exist_ok=True)
    if a.resume and os.path.exists(f"{wd}/report.json"):
        r = json.load(open(f"{wd}/report.json")).get(iid, {})
        return iid, {"resolved": bool(r.get("resolved")), "resumed": True}
    try:
        spec = make_test_spec(inst, namespace="swebench")
    except Exception as e:
        return iid, {"resolved": False, "error": f"test_spec: {type(e).__name__}"}
    open(f"{wd}/patch.diff", "w").write(pred.get("model_patch") or "")
    open(f"{wd}/eval.sh", "w").write(spec.eval_script)
    tries = "\n".join(
        f'if [ $ok = 0 ] && {c} /grade/patch.diff >> /grade/apply.log 2>&1; then ok=1; fi' for c in APPLY)
    open(f"{wd}/grade.sh", "w").write(f"""#!/bin/bash
cd /testbed || {{ echo "{APPLY_PATCH_FAIL}"; echo "no /testbed"; exit 0; }}
ok=0
{tries}
if [ $ok = 0 ]; then echo "{APPLY_PATCH_FAIL}"; cat /grade/apply.log; exit 0; fi
echo "{APPLY_PATCH_PASS}"
git -c core.fileMode=false diff > /grade/git_diff_before.txt 2>&1
/bin/bash /grade/eval.sh
""")
    sif = find_sif(a.sif_dir, iid)
    tout = f"{wd}/test_output.txt"
    if not sif:
        open(tout, "w").write(f"{APPLY_PATCH_FAIL}\nSIF not found\n")
        return iid, {"resolved": False, "error": "no_sif"}
    tdir = os.path.join(a.scratch, a.run_id, f"{iid}-{os.urandom(4).hex()}")
    rmtree_force(tdir); os.makedirs(tdir, exist_ok=True)
    env = dict(os.environ)
    if PX:
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            env[f"APPTAINERENV_{k}"] = PX
        env["APPTAINERENV_NO_PROXY"] = env["APPTAINERENV_no_proxy"] = "localhost,127.0.0.1"
        h, _, port = PX.split("://")[-1].rstrip("/").partition(":")
        env["APPTAINERENV_JAVA_TOOL_OPTIONS"] = (f"-Dhttp.proxyHost={h} -Dhttp.proxyPort={port or 80} -Dhttps.proxyHost={h} "
                                                 f"-Dhttps.proxyPort={port or 80} -Dhttp.nonProxyHosts=localhost|127.0.0.1")
    target = sif
    if a.overlay == "dir":
        ov = os.path.join(tdir, "overlay"); os.makedirs(ov); mode = ["--overlay", ov]
    elif a.overlay == "tmpfs":
        mode = ["--writable-tmpfs"]
    else:
        target = os.path.join(tdir, "sandbox")
        benv = dict(env, APPTAINER_TMPDIR=tdir, APPTAINER_CACHEDIR=os.path.join(tdir, "cache"))
        b = subprocess.run(["apptainer", "build", "--sandbox", target, sif],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=benv)
        if b.returncode != 0:
            open(tout, "w").write(f"{APPLY_PATCH_FAIL}\nsandbox build failed rc={b.returncode}\n"
                                  + b.stdout.decode(errors="ignore")[-2000:])
            return iid, {"resolved": False, "error": "sandbox_build"}
        os.makedirs(os.path.join(target, "grade"), exist_ok=True)
        mode = ["--writable"]
    net = ["--net", "--network", "none"] if NETNS and inst["repo"] in FIXED_PORTS else []
    cmd = ["timeout", "-k", "60", str(a.timeout), "apptainer", "exec", "--fakeroot", "--cleanenv", "--no-home", *net, *mode,
           "--bind", f"{wd}:/grade", "--pwd", "/testbed", target, "bash", "/grade/grade.sh"]
    t0 = time.time()
    repo = inst["repo"]
    lk = None
    if repo in FIXED_PORTS and not NETNS:
        ld = f"/tmp/{os.environ.get('USER', 'u')}/grade_locks"; os.makedirs(ld, exist_ok=True)
        lk = open(f"{ld}/{PORT_GROUP.get(repo, repo).replace('/', '__')}.lock", "w"); fcntl.flock(lk, fcntl.LOCK_EX)
    try:
        with open(tout, "w") as f:
            rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env).returncode
    finally:
        if lk:
            fcntl.flock(lk, fcntl.LOCK_UN); lk.close()
    if rc in (124, 137):
        open(tout, "a").write(f"\n{TESTS_TIMEOUT}\n")
    raw = open(tout, "rb").read()
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        open(tout, "w").write(raw.decode("utf-8", errors="replace"))
    plog = tout
    txt = open(tout, encoding="utf-8", errors="replace").read()
    if any(len(l) > 20000 for l in txt.split("\n")):
        plog = tout + ".parsed"
        open(plog, "w").write("\n".join(l if len(l) <= 20000 else l[:10000] + " [...] " + l[-10000:] for l in txt.split("\n")))
    rep = get_eval_report(test_spec=spec, prediction={"instance_id": iid, "model_patch": pred.get("model_patch") or "",
                          "model_name_or_path": pred.get("model_name_or_path", a.run_id)},
                          test_log_path=plog, include_tests_status=True)
    json.dump(rep, open(f"{wd}/report.json", "w"), indent=1)
    rmtree_force(tdir)
    r = rep.get(iid, {})
    return iid, {"resolved": bool(r.get("resolved")), "rc": rc, "secs": round(time.time() - t0)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--predictions", required=True); ap.add_argument("--dataset", required=True)
    ap.add_argument("--sif-dir", required=True); ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--scratch", default=f"/tmp/{os.environ.get('USER','u')}/gsif")
    ap.add_argument("--workers", type=int, default=8); ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--overlay", choices=["dir", "tmpfs", "sandbox"], default="dir")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--resume", action="store_true", help="skip tasks that already have a report.json")
    a = ap.parse_args()
    ds = {j["instance_id"]: j for j in (json.loads(l) for l in open(a.dataset) if l.strip())}
    ex = set(x for x in a.exclude.split(",") if x)
    preds = [p for p in (json.loads(l) for l in open(a.predictions) if l.strip()) if p["instance_id"] not in ex]
    res = {}
    with cf.ThreadPoolExecutor(a.workers) as pool:
        futs = [pool.submit(grade_one, p, ds[p["instance_id"]], a) for p in preds]
        for fu in cf.as_completed(futs):
            iid, r = fu.result(); res[iid] = r
            print(f"{'RESOLVED  ' if r['resolved'] else 'unresolved'} {iid} {r}", flush=True)
    n = sum(r["resolved"] for r in res.values())
    summ = {"run_id": a.run_id, "total": len(res), "resolved": n, "resolved_ids": sorted(i for i, r in res.items() if r["resolved"]),
            "errors": sorted(i for i, r in res.items() if r.get("error"))}
    spec_err = [i for i, r in res.items() if str(r.get("error", "")).startswith("test_spec")]
    if spec_err:
        print(f"=== {a.run_id}: {len(spec_err)} test_spec failures, summary.json not written: {spec_err[:5]}", flush=True)
    else:
        json.dump(summ, open(os.path.join(a.out, a.run_id, "summary.json"), "w"), indent=1)
    print(f"=== {a.run_id}: resolved {n}/{len(res)}  errors={len(summ['errors'])}")

if __name__ == "__main__":
    main()
