"""HTTP server: the /api/ask endpoint projects call for AI prompts, an
Ollama-compatible proxy that logs local calls, the logging proxy for web APIs
(proxy.py), and the web pages for watching performance and choosing which
provider handles each AI task."""
from __future__ import annotations

import base64
import binascii
import datetime
import json
import time

import httpx
from flask import Flask, Response, jsonify, request, stream_with_context

from service_delegator import config, core, db, gpu, pages, proxy
from service_delegator.providers import PROVIDERS, Image, ProviderError, Request, ollama_metrics, sniff_media_type
from service_delegator.services import SERVICES

app = Flask(__name__)


# ---- /api/ask ----

def _parse_ask(data: dict) -> tuple[Request | None, str | None]:
    """Build a provider Request from an /api/ask body. Returns (request, error)."""
    messages = data.get("messages")
    if messages is None:
        prompt = data.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return None, "Send a prompt (string) or messages (list)"
        messages = [{"role": "user", "content": prompt}]
    if (not isinstance(messages, list) or not messages
            or not all(isinstance(m, dict) and m.get("role") in ("user", "assistant")
                       and isinstance(m.get("content"), str) for m in messages)):
        return None, 'messages must be a list of {"role": "user"|"assistant", "content": "text"}'
    images = []
    for i, im in enumerate(data.get("images") or [], 1):
        b64, media_type = (im, None) if isinstance(im, str) else (im.get("data"), im.get("media_type"))
        try:
            raw = base64.b64decode(b64 or "", validate=True)
            images.append(Image(raw, media_type or sniff_media_type(raw)))
        except (binascii.Error, ValueError, ProviderError) as e:
            return None, f"Image {i}: {e}"
    try:
        max_tokens = int(data["max_tokens"]) if data.get("max_tokens") is not None else 0
        temperature = float(data["temperature"]) if data.get("temperature") is not None else None
        timeout = float(data["timeout"]) if data.get("timeout") is not None else None
    except (TypeError, ValueError):
        return None, "max_tokens, temperature and timeout must be numbers"
    schema = data.get("json_schema")
    if schema is not None and not isinstance(schema, dict):
        return None, "json_schema must be an object"
    extra = data.get("extra") or {}
    if not isinstance(extra, dict):
        return None, "extra must be an object"
    return Request(messages=messages, system=data.get("system"), images=images, max_tokens=max_tokens,
                   temperature=temperature, json_schema=schema, extra=extra, timeout=timeout), None


@app.post("/api/ask")
def api_ask():
    """Body: task (required), project, prompt or messages, and optionally system,
    images (base64 strings or {data, media_type}), max_tokens, temperature,
    json_schema, extra (provider-specific fields), timeout (seconds per provider
    attempt), provider + model (to bypass the task's routes)."""
    data = request.get_json(silent=True) or {}
    task = (data.get("task") or "").strip()
    if not task:
        return jsonify({"error": "task is required (any name; new tasks use the default routes)"}), 400
    provider = data.get("provider")
    if provider is not None and provider not in PROVIDERS:
        return jsonify({"error": f"Unknown provider {provider!r}; one of: {', '.join(PROVIDERS)}"}), 400
    req, err = _parse_ask(data)
    if err:
        return jsonify({"error": err}), 400
    try:
        a = core.ask(task, req, project=data.get("project"), provider=provider, model=data.get("model"))
    except core.DelegatorError as e:
        return jsonify({"error": str(e), "notes": e.notes}), 502
    return jsonify({
        "text": a.text, "provider": a.provider, "model": a.model, "call_id": a.call_id,
        "duration_ms": a.duration_ms, "input_tokens": a.input_tokens, "output_tokens": a.output_tokens,
        "notes": a.notes,
    })


# ---- Ollama-compatible proxy ----
# Point a project's Ollama URL at http://<host>:5055/ollama/<project> and its
# chat/generate calls are logged (with GPU readings); everything else passes
# straight through. An X-Task header names the task for the log.

_LOGGED = {"chat", "generate"}
_HOP_HEADERS = {"content-length", "transfer-encoding", "connection", "content-encoding"}


def _passthrough(path: str) -> Response:
    url = f"{config.ollama_url()}/{path}"
    client = httpx.Client(timeout=None)
    try:
        upstream = client.send(client.build_request(
            request.method, url, params=request.args, content=request.get_data(),
            headers={"Content-Type": request.content_type} if request.content_type else {}), stream=True)
    except httpx.HTTPError as e:
        client.close()
        return jsonify({"error": f"Could not reach Ollama at {config.ollama_url()}: {e}"}), 502

    def body():
        try:
            yield from upstream.iter_raw()
        finally:
            upstream.close()
            client.close()
    headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_HEADERS}
    return Response(stream_with_context(body()), status=upstream.status_code, headers=headers)


def _logged_ollama(path: str, project: str | None) -> Response:
    raw = request.get_data()
    try:
        body = json.loads(raw)
    except ValueError:
        return _passthrough(f"api/{path}")
    if path == "chat":
        msgs = body.get("messages") or []
        preview = next((m.get("content") for m in reversed(msgs) if m.get("role") == "user"), "")
        n_images = sum(len(m.get("images") or []) for m in msgs)
    else:
        preview, n_images = body.get("prompt") or "", len(body.get("images") or [])
    stream = body.get("stream", True)
    conn = db.connect()
    call_id = core.start_call(conn, project=project, task=request.headers.get("X-Task"), provider="ollama",
                              model=body.get("model"), local=True, via="ollama-proxy", n_images=n_images,
                              prompt_preview=preview)
    recorder = gpu.Recorder(call_id).__enter__()
    t0 = time.monotonic()
    url = f"{config.ollama_url()}/api/{path}"

    def finish(status: int, final: dict | None, text: str, error: str | None = None) -> None:
        recorder.__exit__(None, None, None)
        if error is None and status != 200:
            error = (final or {}).get("error") or f"Ollama returned HTTP {status}"
        core.finish_call(conn, call_id, (time.monotonic() - t0) * 1000, error=error,
                         metrics=ollama_metrics(final or {}), text=text)
        conn.close()

    if not stream:
        try:
            resp = httpx.post(url, content=raw, headers={"Content-Type": "application/json"}, timeout=None)
        except httpx.HTTPError as e:
            finish(0, None, "", error=f"Could not reach Ollama: {e}")
            return jsonify({"error": f"Could not reach Ollama at {config.ollama_url()}: {e}"}), 502
        try:
            final = resp.json()
        except ValueError:
            final = {}
        text = (final.get("message") or {}).get("content") if path == "chat" else final.get("response")
        finish(resp.status_code, final, text or "")
        return Response(resp.content, status=resp.status_code,
                        content_type=resp.headers.get("content-type", "application/json"))

    client = httpx.Client(timeout=None)
    try:
        upstream = client.send(client.build_request(
            "POST", url, content=raw, headers={"Content-Type": "application/json"}), stream=True)
    except httpx.HTTPError as e:
        client.close()
        finish(0, None, "", error=f"Could not reach Ollama: {e}")
        return jsonify({"error": f"Could not reach Ollama at {config.ollama_url()}: {e}"}), 502

    def relay():
        pieces, final, error = [], None, None
        try:
            for line in upstream.iter_lines():
                yield line + "\n"
                try:
                    chunk = json.loads(line)
                except ValueError:
                    continue
                if chunk.get("error"):
                    error = chunk["error"]
                pieces.append((chunk.get("message") or {}).get("content", "") if path == "chat"
                              else chunk.get("response", ""))
                if chunk.get("done"):
                    final = chunk
        except httpx.HTTPError as e:
            error = f"Stream from Ollama broke off: {e}"
        except GeneratorExit:
            error = "The client disconnected before the answer finished"
            raise
        finally:
            upstream.close()
            client.close()
            finish(upstream.status_code, final, "".join(pieces), error=error)
    return Response(stream_with_context(relay()), status=upstream.status_code,
                    content_type=upstream.headers.get("content-type", "application/x-ndjson"))


@app.route("/ollama/", defaults={"project": None, "rest": ""}, methods=["GET", "HEAD"])
@app.route("/ollama/<project>/", defaults={"rest": ""}, methods=["GET", "HEAD"])
@app.route("/ollama/api/<path:rest>", defaults={"project": None}, methods=["GET", "POST", "DELETE", "HEAD"])
@app.route("/ollama/<project>/api/<path:rest>", methods=["GET", "POST", "DELETE", "HEAD"])
def ollama_proxy(project, rest):
    if request.method == "POST" and rest in _LOGGED:
        return _logged_ollama(rest, project)
    return _passthrough(f"api/{rest}" if rest else "")


# ---- Web API proxy ----

@app.route("/proxy/<project>/<service>/", defaults={"rest": ""},
           methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
@app.route("/proxy/<project>/<service>/<path:rest>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
def api_proxy(project, service, rest):
    """Forward to the service and log it. Point a project's base URL for a
    service at http://<host>:5055/proxy/<project>/<service>."""
    return proxy.handle(project, service, rest)


# ---- Stats and logs ----

def _since(hours: float | None) -> str:
    if not hours:
        return "0000"
    return (datetime.datetime.now() - datetime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _filters() -> tuple[str, list]:
    where, params = ["started_at >= ?"], [_since(float(request.args.get("hours") or 0))]
    for k in ("project", "provider", "task", "model", "status", "kind"):
        v = request.args.get(k)
        if v:
            if k == "project" and v == "(none)":
                where.append("project IS NULL")
            else:
                where.append(f"{k} = ?")
                params.append(v)
    return " AND ".join(where), params


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(round(p * (len(values) - 1))))], 1)


@app.get("/api/stats")
def api_stats():
    """Per model and per project: call counts, errors, durations, tokens, and
    for local calls the GPU readings. ?hours=N limits to the last N hours."""
    where, params = _filters()
    with db.connect() as conn:
        rows = conn.execute(f"SELECT * FROM calls WHERE {where}", params).fetchall()

    def summarize(group):
        ok = [r for r in group if r["status"] == "ok"]
        durations = [r["duration_ms"] for r in ok if r["duration_ms"] is not None]
        out_tok = sum(r["output_tokens"] or 0 for r in ok)
        gen_ms = sum(r["eval_ms"] or 0 for r in ok if r["eval_ms"])
        gen_tok = sum(r["output_tokens"] or 0 for r in ok if r["eval_ms"])
        local = [r for r in group if r["local"]]
        peak = lambda k: max((r[k] for r in local if r[k] is not None), default=None)
        avg = lambda k: (round(sum(v) / len(v), 1) if (v := [r[k] for r in local if r[k] is not None]) else None)
        return {
            "calls": len(group), "errors": sum(r["status"] == "error" for r in group),
            "unfinished": sum(r["status"] == "running" for r in group),
            "avg_ms": round(sum(durations) / len(durations), 1) if durations else None,
            "p50_ms": _percentile(durations, .5), "p95_ms": _percentile(durations, .95),
            "input_tokens": sum(r["input_tokens"] or 0 for r in ok), "output_tokens": out_tok,
            # Ollama times generation itself; for cloud calls use the whole call
            "tokens_per_s": round(gen_tok / gen_ms * 1000, 1) if gen_ms else
                            (round(out_tok / sum(durations) * 1000, 1) if durations and out_tok else None),
            "last_call": max(r["started_at"] for r in group),
            "peak_junction": peak("gpu_peak_junction"), "avg_junction": avg("gpu_avg_junction"),
            "peak_power": peak("gpu_peak_power"), "peak_fan": peak("gpu_peak_fan"), "peak_cpu": peak("cpu_peak"),
        }

    def grouped(key):
        groups: dict = {}
        for r in rows:
            groups.setdefault(key(r), []).append(r)
        return groups

    by_model = [{"provider": p, "model": m, "kind": g[0]["kind"],
                 "local": PROVIDERS[p].local if p in PROVIDERS else False, **summarize(g)}
                for (p, m), g in grouped(lambda r: (r["provider"], r["model"])).items()]
    by_project = [{"project": p, **summarize(g)} for p, g in grouped(lambda r: r["project"]).items()]
    by_task = [{"task": t, **summarize(g)} for t, g in grouped(lambda r: r["task"]).items()]
    return jsonify({
        "total": summarize(rows) if rows else None,
        "by_model": sorted(by_model, key=lambda x: -x["calls"]),
        "by_project": sorted(by_project, key=lambda x: -x["calls"]),
        "by_task": sorted(by_task, key=lambda x: -x["calls"]),
    })


_CALL_LIST_COLS = ("id, started_at, project, task, provider, model, local, via, kind, endpoint, http_status, "
                   "status, error, duration_ms, "
                   "input_tokens, output_tokens, n_images, eval_ms, gpu_peak_junction, gpu_peak_power, gpu_peak_fan, "
                   "substr(prompt_preview, 1, 160) AS prompt_preview")


@app.get("/api/calls")
def api_calls():
    where, params = _filters()
    limit = min(int(request.args.get("limit", 100)), 1000)
    with db.connect() as conn:
        rows = conn.execute(f"SELECT {_CALL_LIST_COLS} FROM calls WHERE {where} ORDER BY started_at DESC, id DESC LIMIT ?",
                            (*params, limit)).fetchall()
    return jsonify({"calls": [dict(r) for r in rows]})


@app.get("/api/calls/<int:call_id>")
def api_call(call_id):
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
        if row is None:
            return jsonify({"error": "Call not found"}), 404
        samples = conn.execute("SELECT t, edge, junction, mem, power, sclk, fan_rpm, cpu FROM gpu_samples "
                               "WHERE call_id=? ORDER BY t", (call_id,)).fetchall()
    return jsonify({**dict(row), "samples": [dict(s) for s in samples]})


@app.get("/api/filters")
def api_filter_values():
    """Distinct projects, providers and tasks seen, for the filter menus."""
    with db.connect() as conn:
        vals = lambda col: [r[0] if r[0] is not None else "(none)"
                            for r in conn.execute(f"SELECT DISTINCT {col} FROM calls ORDER BY {col}")]
        return jsonify({"projects": vals("project"), "providers": vals("provider"), "tasks": vals("task")})


# ---- Tasks ----

def _task_json(row) -> dict:
    return {"name": row["name"], "description": row["description"], "routes": json.loads(row["routes"]),
            "options": json.loads(row["options"]), "updated_at": row["updated_at"]}


@app.get("/api/tasks")
def api_tasks():
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY name = 'default' DESC, name").fetchall()
        counts = dict(conn.execute("SELECT task, COUNT(*) FROM calls GROUP BY task").fetchall())
    return jsonify({"tasks": [{**_task_json(r), "calls": counts.get(r["name"], 0)} for r in rows]})


@app.put("/api/tasks/<name>")
def api_task_save(name):
    """Create or replace a task: description, routes [{provider, model}], options."""
    data = request.get_json(silent=True) or {}
    name = name.strip()
    if not name:
        return jsonify({"error": "The task needs a name"}), 400
    routes = data.get("routes")
    if not isinstance(routes, list) or not routes:
        return jsonify({"error": "Give at least one provider"}), 400
    clean = []
    for i, r in enumerate(routes, 1):
        if not isinstance(r, dict) or r.get("provider") not in PROVIDERS:
            return jsonify({"error": f"Route {i}: provider must be one of {', '.join(PROVIDERS)}"}), 400
        clean.append({"provider": r["provider"], "model": (r.get("model") or "").strip()
                      or PROVIDERS[r["provider"]].default_model})
    options = data.get("options") or {}
    if not isinstance(options, dict):
        return jsonify({"error": "options must be a JSON object"}), 400
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO tasks (name, description, routes, options, updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET description=excluded.description, routes=excluded.routes, "
            "options=excluded.options, updated_at=excluded.updated_at",
            (name, (data.get("description") or "").strip() or None, json.dumps(clean), json.dumps(options), core.now()),
        )
    return jsonify({"ok": True})


@app.delete("/api/tasks/<name>")
def api_task_delete(name):
    if name == "default":
        return jsonify({"error": "The default task can't be deleted"}), 400
    with db.connect() as conn:
        if conn.execute("DELETE FROM tasks WHERE name=?", (name,)).rowcount == 0:
            return jsonify({"error": "Task not found"}), 404
    return jsonify({"ok": True})


@app.post("/api/tasks/<name>/test")
def api_task_test(name):
    prompt = (request.get_json(silent=True) or {}).get("prompt") or "What is 2+2? Reply with just the number."
    try:
        a = core.ask(name, Request(messages=[{"role": "user", "content": prompt}], max_tokens=0),
                     project="service-delegator test")
    except core.DelegatorError as e:
        return jsonify({"error": str(e), "notes": e.notes}), 502
    return jsonify({"text": a.text, "provider": a.provider, "model": a.model, "duration_ms": a.duration_ms,
                    "call_id": a.call_id, "notes": a.notes})


# ---- Providers ----

@app.get("/api/providers")
def api_providers():
    out = []
    with db.connect() as conn:
        for p in PROVIDERS.values():
            last_err = conn.execute(
                "SELECT started_at, error FROM calls WHERE provider=? AND status='error' ORDER BY id DESC LIMIT 1",
                (p.name,)).fetchone()
            out.append({"name": p.name, "display": p.display, "configured": p.configured(), "local": p.local,
                        "default_model": p.default_model, "key_url": p.key_url,
                        "cooling_off": core._cooling_off(conn, p.name),
                        "last_error": dict(last_err) if last_err else None})
    ollama = {"url": config.ollama_url(), "models": [], "error": None}
    try:
        resp = httpx.get(f"{config.ollama_url()}/api/tags", timeout=5)
        resp.raise_for_status()
        ollama["models"] = [m["name"] for m in resp.json().get("models", [])]
    except (httpx.HTTPError, ValueError) as e:
        ollama["error"] = f"Could not list Ollama models: {e}"
    return jsonify({"providers": out, "ollama": ollama, "sensors": gpu.sensors_found()})


@app.post("/api/providers/<name>/test")
def api_provider_test(name):
    if name not in PROVIDERS:
        return jsonify({"error": "Unknown provider"}), 404
    model = (request.get_json(silent=True) or {}).get("model") or PROVIDERS[name].default_model
    try:
        a = core.ask("provider-test", Request(messages=[{"role": "user", "content":
                     "What is 2+2? Reply with just the number."}], max_tokens=0),
                     project="service-delegator test", provider=name, model=model)
    except core.DelegatorError as e:
        return jsonify({"error": "; ".join(e.notes) or str(e)}), 502
    return jsonify({"text": a.text, "model": a.model, "duration_ms": a.duration_ms, "call_id": a.call_id})


@app.get("/api/services")
def api_services():
    """The web APIs the proxy knows, with each one's numbers over ?hours=N
    (default a week)."""
    hours = float(request.args.get("hours") or 168)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT provider, COUNT(*) AS calls, SUM(status='error') AS errors, AVG(duration_ms) AS avg_ms, "
            "MAX(started_at) AS last_call, GROUP_CONCAT(DISTINCT project) AS projects "
            "FROM calls WHERE kind='api' AND started_at >= ? GROUP BY provider", (_since(hours),)).fetchall()
        stats = {r["provider"]: dict(r) for r in rows}
        out = []
        for s in SERVICES.values():
            last_err = conn.execute(
                "SELECT started_at, error FROM calls WHERE provider=? AND kind='api' AND status='error' "
                "ORDER BY id DESC LIMIT 1", (s.name,)).fetchone()
            st = stats.get(s.name, {})
            out.append({"name": s.name, "display": s.display, "base_url": s.base_url, "used_by": s.used_by,
                        "notes": s.notes, "calls": st.get("calls", 0), "errors": st.get("errors", 0),
                        "avg_ms": round(st["avg_ms"], 1) if st.get("avg_ms") is not None else None,
                        "last_call": st.get("last_call"), "projects": st.get("projects"),
                        "last_error": dict(last_err) if last_err else None})
    return jsonify({"services": out})


# ---- Pages ----

@app.get("/")
def overview_page():
    return Response(pages.OVERVIEW, mimetype="text/html")


@app.get("/calls/<int:call_id>")
def call_page(call_id):
    return Response(pages.CALL.replace("__CALL_ID__", str(call_id)), mimetype="text/html")


@app.get("/tasks")
def tasks_page():
    return Response(pages.TASKS, mimetype="text/html")


@app.get("/services")
def services_page():
    return Response(pages.SERVICES, mimetype="text/html")


def run(host: str, port: int) -> None:
    db.init()
    app.run(host=host, port=port, threaded=True)
