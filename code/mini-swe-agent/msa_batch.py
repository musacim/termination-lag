#!/usr/bin/env python3
"""Run mini-SWE-agent on a list of SWE-bench tasks with several parallel workers.
usage: msa_batch.py --pool D --tasks F --dataset F --sif-dir D --meta F --ws-root D --out D --api-base URL --model NAME"""
import argparse, concurrent.futures as cf, fcntl, glob, json, os, socket, subprocess, threading, time, traceback
import yaml
from pathlib import Path
from litellm.responses.mcp.chat_completions_handler import acompletion_with_mcp
from minisweagent.agents.default import DefaultAgent
from minisweagent.config import builtin_config_dir
from minisweagent.environments.singularity import SingularityEnvironment
from minisweagent.models import get_model
from minisweagent.models.litellm_model import LitellmModel

ap = argparse.ArgumentParser()
for x in ("pool", "tasks", "dataset", "sif-dir", "meta", "ws-root", "out", "api-base", "model"):
    ap.add_argument(f"--{x}", required=True)
ap.add_argument("--workers", type=int, default=10); ap.add_argument("--step-limit", type=int, default=100)
ap.add_argument("--temp", type=float, default=0.7); ap.add_argument("--deadline", type=float, default=0)
ap.add_argument("--min-left", type=int, default=1500)
a = ap.parse_args()
CFG = yaml.safe_load(open(builtin_config_dir / "benchmarks" / "swebench.yaml"))
META = json.load(open(a.meta)); DS = {j["instance_id"]: j for j in map(json.loads, open(a.dataset))}
JOB = os.environ.get("JOB_ID", "local").split(".")[0]; HOST = socket.gethostname().split(".")[0]
for d in (f"{a.out}/trajectories", f"{a.pool}/claims", f"{a.pool}/done", f"{a.pool}/stale", a.ws_root):
    os.makedirs(d, exist_ok=True)
IDS = [l.strip() for l in open(a.tasks) if l.strip()]
lock = threading.Lock()


def job_ended(j):
    cmd = os.environ.get("JOB_ENDED_CMD")
    return bool(cmd) and subprocess.run(cmd.format(job=j), shell=True, capture_output=True).returncode == 0


def claim():
    for iid in IDS:
        if os.path.exists(f"{a.pool}/done/{iid}"):
            continue
        c = f"{a.pool}/claims/{iid}"
        try:
            os.mkdir(c)
        except FileExistsError:
            try:
                host, j = open(f"{c}/by").read().split()
            except Exception:
                continue
            if j == JOB or not job_ended(j):
                continue
            st = f"{a.pool}/stale/{iid}.{j}.{time.time_ns()}"
            try:
                os.rename(c, st)
            except OSError:
                continue
            try:
                moved = open(f"{st}/by").read().split()[1]
            except Exception:
                moved = None
            if moved != j:
                try:
                    os.rename(st, c)
                except OSError:
                    pass
                continue
            try:
                os.mkdir(c)
            except OSError:
                continue
        open(f"{c}/by", "w").write(f"{HOST} {JOB}\n")
        return iid
    return None


BUILD_SLOTS = int(os.environ.get("MSA_BUILD_SLOTS", "4"))


def build_slot():
    d = f"/tmp/{os.environ.get('USER', 'u')}/msa_slots"; os.makedirs(d, exist_ok=True)
    while True:
        for k in range(BUILD_SLOTS):
            f = open(f"{d}/slot{k}", "w")
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return f
            except BlockingIOError:
                f.close()
        time.sleep(2)


def strip_mode_only(d):
    import re
    keep = [b for b in re.split(r"(?m)^(?=diff --git )", d)
            if b and any(l.startswith(("@@", "Binary files", "new file mode", "deleted file mode", "rename ")) for l in b.splitlines())]
    return "".join(keep)


def full_diff(repo, base):
    cmd = (f"idx=$(mktemp) && export GIT_INDEX_FILE=$idx && g='git -c safe.directory=* -c core.fileMode=false -C {repo}' && "
           f"$g read-tree HEAD && $g add -A && $g --no-pager diff --cached --no-color {base}; rc=$?; rm -f $idx; exit $rc")
    p = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, errors="replace")
    return p.stdout if p.returncode == 0 else ""


def run(iid):
    t0 = time.time(); m = META[iid]; rec = {"instance_id": iid, "host": HOST, "job": JOB}
    sif = sorted(glob.glob(f"{a.sif_dir}/*sweb.eval.x86_64.{iid.split('__')[0]}_1776_{iid.split('__', 1)[1]}-*.sif"))
    env = agent = None; link = f"{a.ws_root}/{iid}-attempt1-msa"
    try:
        env_cfg = {k: v for k, v in CFG["environment"].items() if k not in ("environment_class", "interpreter")}
        slot = build_slot()
        try:
            env = SingularityEnvironment(image=sif[0], executable="apptainer", **env_cfg, sandbox_build_retries=1,
                                         exec_args=["--fakeroot", "--cleanenv", "--no-home"])
        finally:
            fcntl.flock(slot, fcntl.LOCK_UN); slot.close()
        os.makedirs(link, exist_ok=True)
        if not os.path.islink(f"{link}/{m['repo']}"):
            os.symlink(f"{env.sandbox_dir}/testbed", f"{link}/{m['repo']}")
        model = get_model(config={**CFG.get("model", {}), "model_name": f"openai/{a.model}", "cost_tracking": "ignore_errors",
                                  "model_kwargs": {"api_base": a.api_base, "api_key": "none", "temperature": a.temp,
                                                   "timeout": 1800, "max_retries": 0}})
        agent = DefaultAgent(model, env, **{**CFG["agent"], "step_limit": a.step_limit, "cost_limit": 0})
        info = agent.run(DS[iid]["problem_statement"])
        rec.update(exit_status=info.get("exit_status"), submission=info.get("submission") or "")
    except Exception as e:
        rec.update(exit_status=type(e).__name__, submission="", error=traceback.format_exc()[-2000:])
    finally:
        rec["final_diff"] = full_diff(f"{env.sandbox_dir}/testbed", m["base"]) if env else ""
        rec["steps"] = getattr(agent, "n_calls", None); rec["secs"] = round(time.time() - t0)
        if agent is not None:
            try:
                agent.save(Path(f"{a.out}/trajectories/{iid}.traj.json"),
                           
                           {"instance_id": iid, "info": {k: rec.get(k) for k in ("exit_status", "submission")}})
            except Exception as e:
                rec["save_error"] = repr(e)[:200]
        if env is not None:
            env.cleanup()
        try:
            os.unlink(f"{link}/{m['repo']}"); os.rmdir(link)
        except OSError:
            pass
        with lock:
            with open(f"{a.out}/output.jsonl", "a") as f:
                f.write(json.dumps(rec) + "\n")
            with open(f"{a.out}/instances.txt", "a") as f:
                f.write(iid + "\n")
            with open(f"{a.out}/trajectories/output.jsonl", "a") as f:
                f.write(json.dumps({"instance_id": iid, "test_result": {"git_patch": strip_mode_only(rec["final_diff"])},
                                    "error": None if rec["exit_status"] == "Submitted" else rec["exit_status"]}) + "\n")
        open(f"{a.pool}/done/{iid}", "w").write(f"{HOST} {JOB} {rec['exit_status']}\n")
        print(f"{time.strftime('%T')} {iid} {rec['exit_status']} steps={rec['steps']} secs={rec['secs']}", flush=True)


def worker():
    while True:
        if a.deadline and time.time() > a.deadline - a.min_left:
            return
        with lock:
            iid = claim()
        if iid is None:
            return
        run(iid)


print(f"msa_batch {HOST} job {JOB}: {a.workers} workers, out {a.out}", flush=True)
with cf.ThreadPoolExecutor(a.workers) as ex:
    for _ in range(a.workers):
        ex.submit(worker)
print(f"msa_batch {HOST} done", flush=True)
