"""Sending a prompt for a task: pick the provider from the task's routes,
call it, and log the call.

A task's routes are tried in order. A provider without an API key is
skipped, as is one that failed in the last few minutes (a cool-off, as in
radioserver) unless it's the last route left. Every attempt is logged as its
own row in `calls`; local (Ollama) calls also record GPU readings.
"""
from __future__ import annotations

import datetime
import json
import time
from dataclasses import dataclass, field

from service_delegator import db, gpu
from service_delegator.providers import PROVIDERS, ProviderError, Request, Result

COOLOFF_MINUTES = 5
PREVIEW_CHARS = 2000


def now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Answer:
    text: str
    provider: str
    model: str
    call_id: int
    duration_ms: float
    input_tokens: int | None
    output_tokens: int | None
    notes: list[str] = field(default_factory=list)   # earlier routes that were skipped or failed


class DelegatorError(Exception):
    def __init__(self, message: str, notes: list[str] | None = None):
        super().__init__(message)
        self.notes = notes or []


def get_task(conn, name: str) -> dict:
    """The task's settings. A task seen for the first time is created with
    the default task's routes, so it shows up on the Tasks page to be set up."""
    row = conn.execute("SELECT * FROM tasks WHERE name=?", (name,)).fetchone()
    if row is None:
        default = conn.execute("SELECT routes, options FROM tasks WHERE name='default'").fetchone()
        conn.execute(
            "INSERT INTO tasks (name, description, routes, options, updated_at) VALUES (?,?,?,?,?)",
            (name, "Created on first use with the default routes", default["routes"], default["options"], now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE name=?", (name,)).fetchone()
    return {"name": row["name"], "routes": json.loads(row["routes"]), "options": json.loads(row["options"])}


def _cooling_off(conn, provider: str) -> str | None:
    """Why the provider is resting, if its latest call failed in the last few minutes."""
    row = conn.execute(
        "SELECT status, error, started_at FROM calls WHERE provider=? AND status != 'running' "
        "ORDER BY id DESC LIMIT 1", (provider,)
    ).fetchone()
    if row is None or row["status"] != "error":
        return None
    when = datetime.datetime.strptime(row["started_at"], "%Y-%m-%d %H:%M:%S")
    if datetime.datetime.now() - when > datetime.timedelta(minutes=COOLOFF_MINUTES):
        return None
    return f"skipped for a {COOLOFF_MINUTES}-minute cool-off after an error at {when:%H:%M}: {(row['error'] or '')[:120]}"


def start_call(conn, *, project, task, provider, model, local, via, n_images, prompt_preview) -> int:
    cur = conn.execute(
        "INSERT INTO calls (started_at, project, task, provider, model, local, via, status, n_images, prompt_preview) "
        "VALUES (?,?,?,?,?,?,?, 'running', ?, ?)",
        (now(), project, task, provider, model, int(local), via, n_images, (prompt_preview or "")[:PREVIEW_CHARS]),
    )
    conn.commit()
    return cur.lastrowid


def finish_call(conn, call_id: int, duration_ms: float, result: Result | None = None,
                error: str | None = None, metrics: dict | None = None, text: str | None = None) -> None:
    m = dict(metrics or {})
    if result is not None:
        m.update(input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                 cache_read_tokens=result.cache_read_tokens, load_ms=result.load_ms,
                 prompt_eval_ms=result.prompt_eval_ms, eval_ms=result.eval_ms)
        text = result.text
    cols = {k: m.get(k) for k in ("input_tokens", "output_tokens", "cache_read_tokens",
                                  "load_ms", "prompt_eval_ms", "eval_ms")}
    conn.execute(
        f"UPDATE calls SET status=?, error=?, duration_ms=?, response_preview=?, "
        f"{', '.join(f'{k}=?' for k in cols)} WHERE id=?",
        ("error" if error else "ok", error, round(duration_ms, 1), (text or "")[:PREVIEW_CHARS],
         *cols.values(), call_id),
    )
    conn.commit()


def ask(task_name: str, req: Request, project: str | None = None,
        provider: str | None = None, model: str | None = None) -> Answer:
    """Send the request using the task's routes (or the given provider/model
    instead). Raises DelegatorError if no route gives an answer."""
    conn = db.connect()
    try:
        task = get_task(conn, task_name)
        routes = [{"provider": provider, "model": model}] if provider else task["routes"]
        if not routes:
            raise DelegatorError(f"Task {task_name!r} has no providers set up")
        opts = task["options"]
        notes: list[str] = []
        prompt_preview = req.messages[-1]["content"] if req.messages else ""
        for i, route in enumerate(routes):
            p = PROVIDERS.get(route["provider"])
            if p is None:
                notes.append(f"{route['provider']}: unknown provider")
                continue
            if not p.configured():
                notes.append(f"{p.name}: no API key (run: service-delegator set-key {p.name} KEY)")
                continue
            last = i == len(routes) - 1
            if not last and (why := _cooling_off(conn, p.name)):
                notes.append(f"{p.name}: {why}")
                continue
            use_model = route.get("model") or p.default_model
            # Task options fill in whatever the caller didn't set
            r = Request(
                messages=req.messages, system=req.system, images=req.images,
                max_tokens=req.max_tokens if req.max_tokens else opts.get("max_tokens", 4096),
                temperature=req.temperature if req.temperature is not None else opts.get("temperature"),
                json_schema=req.json_schema,
                extra={**p.default_extra, **opts.get("extra", {}).get(p.name, {}), **req.extra},
                timeout=req.timeout or opts.get("timeout"),
            )
            call_id = start_call(conn, project=project, task=task_name, provider=p.name, model=use_model,
                                 local=p.local, via="ask", n_images=len(req.images), prompt_preview=prompt_preview)
            t0 = time.monotonic()
            try:
                if p.local:
                    with gpu.Recorder(call_id):
                        result = p.ask(r, use_model)
                else:
                    result = p.ask(r, use_model)
            except Exception as e:
                msg = str(e) if isinstance(e, ProviderError) else f"{type(e).__name__}: {e}"
                finish_call(conn, call_id, (time.monotonic() - t0) * 1000, error=msg)
                notes.append(f"{p.name}: {msg}")
                continue
            duration = (time.monotonic() - t0) * 1000
            finish_call(conn, call_id, duration, result=result)
            return Answer(text=result.text, provider=p.name, model=use_model, call_id=call_id,
                          duration_ms=round(duration, 1), input_tokens=result.input_tokens,
                          output_tokens=result.output_tokens, notes=notes)
        raise DelegatorError(f"No provider answered for task {task_name!r}", notes)
    finally:
        conn.close()
