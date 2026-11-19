#!/usr/bin/env python3
"""Proxy between the agent and the model server: logs every model call and saves the repository patch before each call.
usage: stepproxy.py <listen_port> <upstream_port> <out.jsonl>"""
import asyncio, glob, hashlib, json, os, sys, time
import aiohttp
from aiohttp import web

LISTEN, UP, OUT = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
BASE = f"http://127.0.0.1:{UP}"
inflight = set()
SNAP_EVERY = int(os.environ.get("STEPPROXY_SNAP_EVERY") or 0)
SNAP_DIR = os.environ.get("STEPPROXY_SNAP_DIR", "")
META = json.load(open(os.environ["STEPPROXY_TASK_META"])) if SNAP_EVERY else {}
conv_task = {}
WS_ROOT = os.environ.get("OPENHANDS_APPTAINER_WORKSPACE_ROOT") or os.environ.get("TMPDIR", "/tmp")
WS_GLOB = "" if os.environ.get("OPENHANDS_APPTAINER_WORKSPACE_ROOT") else "openhands-apptainer-workspaces-*/"
log = open(OUT, "a", buffering=1)


async def snapshot(iid, step):
    m = META[iid]
    ws = sorted(glob.glob(f"{WS_ROOT}/{WS_GLOB}{iid}-attempt*-*/{m['repo']}"), key=os.path.getmtime)
    if not ws:
        return "no-workspace"
    os.makedirs(f"{SNAP_DIR}/{iid}", exist_ok=True)
    out = f"{SNAP_DIR}/{iid}/step{step:03d}.diff"
    cmd = (f"idx=$(mktemp) && export GIT_INDEX_FILE=$idx && g='git -c safe.directory=* -c core.fileMode=false -C {ws[-1]}' && "
           f"$g read-tree HEAD && $g add -A && $g --no-pager diff --cached --no-color {m['base']} > {out}.tmp "
           f"&& mv {out}.tmp {out}; rc=$?; rm -f $idx; exit $rc")
    p = await asyncio.create_subprocess_exec("bash", "-c", cmd, stdout=asyncio.subprocess.DEVNULL,
                                             stderr=asyncio.subprocess.PIPE)
    _, err = await p.communicate()
    return os.path.getsize(out) if p.returncode == 0 else f"error: {err.decode()[-200:]}"


def refuse(rec, why):
    rec["status"] = 400
    log.write(json.dumps(rec) + "\n")
    err = {"error": {"message": f"stepproxy: {why}", "type": "BadRequestError", "code": 400}}
    return web.Response(body=json.dumps(err).encode(), status=400, content_type="application/json")


def first_user(msgs):
    for m in msgs:
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
            return c or ""
    return ""


async def chat(req):
    body = await req.json()
    msgs = body.get("messages") or []
    t0 = time.time()
    fu = first_user(msgs)
    conv, step = hashlib.sha1(fu.encode()).hexdigest()[:16], sum(1 for m in msgs if m.get("role") == "assistant")
    rec = {"conv": conv, "step": step, "t0": round(t0, 3)}
    if step == 0:
        rec["head"] = fu[:3000]
        if META:
            h = " ".join(fu.split())
            hit = [i for i, m in META.items() if m["key"] in h]
            if len(hit) == 1:
                conv_task[conv] = hit[0]
    if SNAP_EVERY and step and step % SNAP_EVERY == 0 and conv in conv_task:
        rec["snap"] = await snapshot(conv_task[conv], step)
    if (conv, step) in inflight:
        rec.update(t1=rec["t0"], resend=True)
        return refuse(rec, "repeat of an in-flight request refused (no retries)")
    inflight.add((conv, step))
    try:
        async with req.app["s"].post(f"{BASE}{req.path}", json=body) as r:
            status, data = r.status, await r.read()
    finally:
        inflight.discard((conv, step))
    rec.update(t1=round(time.time(), 3), status=status)
    if status == 200:
        d = json.loads(data); u = d.get("usage") or {}
        rec.update(prompt_tokens=u.get("prompt_tokens"), completion_tokens=u.get("completion_tokens"),
                   cached_tokens=(u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                   finish_reason=((d.get("choices") or [{}])[0]).get("finish_reason"))
    else:
        rec["error"] = data[:500].decode(errors="replace")
    log.write(json.dumps(rec) + "\n")
    return web.Response(body=data, status=status, content_type="application/json")


async def passthrough(req):
    async with req.app["s"].request(req.method, f"{BASE}{req.path_qs}", data=await req.read()) as r:
        return web.Response(body=await r.read(), status=r.status,
                            content_type=r.content_type or "application/octet-stream")


async def start(app):
    app["s"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None),
                                     connector=aiohttp.TCPConnector(limit=0))


async def stop(app):
    await app["s"].close()


app = web.Application(client_max_size=256 * 1024 * 1024)
app.on_startup.append(start); app.on_cleanup.append(stop)
app.router.add_post("/v1/chat/completions", chat)
app.router.add_route("*", "/{tail:.*}", passthrough)
web.run_app(app, host="127.0.0.1", port=LISTEN, access_log=None, print=None)
