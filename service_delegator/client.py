"""Client for projects that send prompts through the delegator.

Uses only the standard library, so a project can depend on service-delegator or
simply copy this file.

    from service_delegator.client import ask

    answer = ask("song-year", "What year was 'Yesterday' by The Beatles released?",
                 project="radioserver", max_tokens=20)
    print(answer["text"], answer["provider"], answer["duration_ms"])

The server is at $SERVICE_DELEGATOR_URL, default http://127.0.0.1:5055.
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:5055"


class DelegatorError(Exception):
    def __init__(self, message: str, notes: list[str] | None = None):
        super().__init__(message + (f" ({'; '.join(notes)})" if notes else ""))
        self.notes = notes or []


def ask(task: str, prompt: str | None = None, *, project: str | None = None,
        messages: list[dict] | None = None, system: str | None = None,
        images: list[bytes] | None = None, max_tokens: int | None = None,
        temperature: float | None = None, json_schema: dict | None = None,
        provider: str | None = None, model: str | None = None, extra: dict | None = None,
        provider_timeout: float | None = None, url: str | None = None, timeout: float = 900) -> dict:
    """Send a prompt for `task` and return the server's answer:
    {text, provider, model, call_id, duration_ms, input_tokens, output_tokens, notes}.
    provider_timeout limits each provider attempt; timeout is for the whole HTTP request.
    Raises DelegatorError when no provider answers or the server can't be reached."""
    body = {"task": task, "project": project}
    if messages is not None:
        body["messages"] = messages
    else:
        body["prompt"] = prompt
    for k, v in (("system", system), ("max_tokens", max_tokens), ("temperature", temperature),
                 ("json_schema", json_schema), ("provider", provider), ("model", model), ("extra", extra),
                 ("timeout", provider_timeout)):
        if v is not None:
            body[k] = v
    if images:
        body["images"] = [base64.standard_b64encode(im).decode("ascii") for im in images]
    base = (url or os.environ.get("SERVICE_DELEGATOR_URL") or DEFAULT_URL).rstrip("/")
    req = urllib.request.Request(f"{base}/api/ask", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            data = json.load(e)
        except ValueError:
            raise DelegatorError(f"service delegator returned HTTP {e.code}")
        raise DelegatorError(data.get("error") or f"HTTP {e.code}", data.get("notes"))
    except urllib.error.URLError as e:
        raise DelegatorError(f"Could not reach the service delegator at {base}: {e.reason}")
