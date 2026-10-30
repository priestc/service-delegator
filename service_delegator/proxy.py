"""The logging proxy for web APIs: /proxy/<project>/<service>/<path>.

The request is forwarded to the service's base URL as-is and the response
streamed back. One row in `calls` (kind 'api') records the endpoint, status,
duration and sizes. Responses are passed back uncompressed so an error body
can be read into the log.
"""
from __future__ import annotations

import time
import urllib.parse

import httpx
from flask import Response, jsonify, request, stream_with_context

from service_delegator import core, db
from service_delegator.services import SERVICES

# Request headers that belong to this hop, or are the delegator's own
_DROP_REQUEST = {"host", "content-length", "connection", "transfer-encoding", "accept-encoding",
                 "keep-alive", "x-task", "x-project"}
# Response headers that no longer apply once the body is decoded and re-streamed
_DROP_RESPONSE = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive"}
ERROR_BODY_CHARS = 500

_clients: dict[bool, httpx.Client] = {}


def _client(http2: bool) -> httpx.Client:
    # Shared so connections (and Apple Push's HTTP/2 session) are reused
    if http2 not in _clients:
        _clients[http2] = httpx.Client(http2=http2, follow_redirects=False,
                                       timeout=httpx.Timeout(120, connect=10))
    return _clients[http2]


def handle(project: str, service: str, rest: str) -> Response:
    svc = SERVICES.get(service)
    if svc is None:
        return jsonify({"error": f"Unknown service {service!r}. Known: {', '.join(SERVICES)}"}), 404
    url = f"{svc.base_url}/{rest}"
    query = request.query_string.decode()
    body = request.get_data()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _DROP_REQUEST}
    endpoint = f"{request.method} {urllib.parse.urlsplit(url).path}"

    conn = db.connect()
    call_id = core.start_call(conn, project=project, task=request.headers.get("X-Task"), provider=svc.name,
                              model=None, local=False, via="proxy", n_images=0,
                              prompt_preview=endpoint + (f"?{query}" if query else ""))
    conn.execute("UPDATE calls SET kind='api', endpoint=?, bytes_sent=? WHERE id=?", (endpoint, len(body), call_id))
    conn.commit()
    t0 = time.monotonic()

    def finish(status: int | None, received: int, error: str | None) -> None:
        conn.execute(
            "UPDATE calls SET status=?, error=?, duration_ms=?, http_status=?, bytes_received=? WHERE id=?",
            ("error" if error else "ok", error, round((time.monotonic() - t0) * 1000, 1), status, received, call_id))
        conn.commit()
        conn.close()

    client = _client(svc.http2)
    try:
        upstream = client.send(client.build_request(request.method, url, params=query or None, content=body,
                                                    headers=headers), stream=True)
    except httpx.HTTPError as e:
        msg = f"Could not reach {svc.display}: {type(e).__name__}: {e}"
        finish(None, 0, msg)
        return jsonify({"error": msg, "service": svc.name}), 502

    out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _DROP_RESPONSE}
    # A relative redirect would otherwise point back at the delegator
    if (loc := upstream.headers.get("location", "")).startswith("/"):
        parts = urllib.parse.urlsplit(svc.base_url)
        out_headers["location"] = f"{parts.scheme}://{parts.netloc}{loc}"

    def relay():
        received, head, error = 0, b"", None
        try:
            for chunk in upstream.iter_bytes():
                received += len(chunk)
                if upstream.status_code >= 400 and len(head) < ERROR_BODY_CHARS:
                    head += chunk[:ERROR_BODY_CHARS - len(head)]
                yield chunk
        except httpx.HTTPError as e:
            error = f"Response from {svc.display} broke off: {e}"
        except GeneratorExit:
            error = "The client disconnected before the response finished"
            raise
        finally:
            upstream.close()
            if error is None and upstream.status_code >= 400:
                text = head.decode("utf-8", "replace").strip()
                error = f"HTTP {upstream.status_code}" + (f": {text}" if text else "")
            finish(upstream.status_code, received, error)

    return Response(stream_with_context(relay()), status=upstream.status_code, headers=out_headers)
