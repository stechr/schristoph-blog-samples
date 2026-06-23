"""
Lambda MicroVMs demo sandbox.

A tiny HTTP service that runs INSIDE a Firecracker microVM and executes
(AI-generated) Python code in a persistent, per-session namespace.

Two servers run in one process:
  * Application API on port 8080  (the proxy routes ingress traffic here)
  * Lifecycle hooks on port 9000  (the platform calls these)

Application endpoints (8080):
  GET  /            -> liveness + VM identity
  GET  /state       -> what this session knows: vars, counter, files, identity
  POST /exec        -> run a Python snippet in a persistent namespace
  GET  /healthz     -> simple health probe

Lifecycle hooks (9000, paths under /aws/lambda-microvms/runtime/v1):
  POST .../ready      image build hook: 200 once booted -> snapshot is taken here
  POST .../validate   image build hook: exercise app so platform prefetches snapshot
  POST .../run        runtime hook: fires ONCE after launch-from-snapshot.
                      We RESEED identity so microVMs cloned from one snapshot
                      are not identical (snapshot-uniqueness pitfall).
  POST .../resume     runtime hook: after SUSPENDED -> RUNNING (reseed CSPRNG)
  POST .../suspend    runtime hook: before RUNNING -> SUSPENDED
  POST .../terminate  runtime hook: before termination
"""
from __future__ import annotations  # allow `str | None` hints on Python 3.9

import io
import os
import time
import uuid
import random
import secrets
import threading
import contextlib
import traceback

from flask import Flask, request, jsonify

# ---- Application API (port 8080) -------------------------------------------
app = Flask(__name__)

BOOT_TIME = time.time()

# Persistent per-session execution namespace. Lives in microVM memory, which the
# snapshot preserves across suspend/resume.
SESSION_NS: dict = {"__name__": "sandbox"}

STATE = {
    "exec_count": 0,
    # Set at import time => identical across every microVM from the same snapshot.
    # The /run hook reseeds it so each running microVM has a distinct identity.
    "vm_instance_id": "unseeded-" + uuid.uuid4().hex[:8],
    "reseeded": False,
    "microvm_id": None,
}


def _reseed_identity(reason: str, microvm_id: str | None = None):
    random.seed(secrets.token_bytes(32))
    STATE["vm_instance_id"] = uuid.uuid4().hex
    STATE["reseeded"] = True
    STATE["reseed_reason"] = reason
    if microvm_id:
        STATE["microvm_id"] = microvm_id


@app.get("/")
def root():
    return jsonify(
        service="lambda-microvms-sandbox",
        message="Isolated Firecracker sandbox, ready for code.",
        vm_instance_id=STATE["vm_instance_id"],
        hostname=os.uname().nodename,
        uptime_seconds=round(time.time() - BOOT_TIME, 1),
    )


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


@app.get("/state")
def state():
    user_vars = {
        k: repr(v)[:120] for k, v in SESSION_NS.items() if not k.startswith("__")
    }
    try:
        workspace = sorted(os.listdir("/workspace"))
    except FileNotFoundError:
        workspace = []
    return jsonify(
        vm_instance_id=STATE["vm_instance_id"],
        reseeded=STATE["reseeded"],
        microvm_id=STATE["microvm_id"],
        hostname=os.uname().nodename,
        exec_count=STATE["exec_count"],
        session_vars=user_vars,
        workspace_files=workspace,
        uptime_seconds=round(time.time() - BOOT_TIME, 1),
    )


@app.post("/exec")
def execute():
    payload = request.get_json(force=True, silent=True) or {}
    code = payload.get("code", "")
    if not code:
        return jsonify(error="no 'code' provided"), 400

    STATE["exec_count"] += 1
    stdout = io.StringIO()
    result = None
    error = None
    started = time.time()
    try:
        with contextlib.redirect_stdout(stdout):
            exec(compile(code, "<sandbox>", "exec"), SESSION_NS)  # noqa: S102
            result = SESSION_NS.get("RESULT")
    except Exception:  # noqa: BLE001
        error = traceback.format_exc()

    return jsonify(
        ok=error is None,
        exec_count=STATE["exec_count"],
        stdout=stdout.getvalue(),
        result=repr(result) if result is not None else None,
        error=error,
        duration_ms=round((time.time() - started) * 1000, 1),
        vm_instance_id=STATE["vm_instance_id"],
    )


# ---- Lifecycle hooks (port 9000) -------------------------------------------
hooks = Flask("hooks")
HP = "/aws/lambda-microvms/runtime/v1"


@hooks.post(f"{HP}/ready")
def ready():
    # App is booted; safe to snapshot.
    return jsonify(ready=True), 200


@hooks.post(f"{HP}/validate")
def validate():
    try:
        exec(compile("RESULT = sum(range(1000))", "<validate>", "exec"), dict(SESSION_NS))
        return jsonify(valid=True), 200
    except Exception:  # noqa: BLE001
        return jsonify(valid=False, error=traceback.format_exc()), 503


@hooks.post(f"{HP}/run")
def run_hook():
    body = request.get_json(force=True, silent=True) or {}
    _reseed_identity("run", microvm_id=body.get("microvmId"))
    return jsonify(ok=True, vm_instance_id=STATE["vm_instance_id"]), 200


@hooks.post(f"{HP}/resume")
def resume_hook():
    random.seed(secrets.token_bytes(32))
    return jsonify(ok=True), 200


@hooks.post(f"{HP}/suspend")
def suspend_hook():
    return jsonify(ok=True), 200


@hooks.post(f"{HP}/terminate")
def terminate_hook():
    return jsonify(ok=True), 200


def _serve_hooks():
    hooks.run(host="0.0.0.0", port=9000, threaded=True)


if __name__ == "__main__":
    threading.Thread(target=_serve_hooks, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, threaded=True)
