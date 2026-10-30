"""The AI services prompts can be sent to, behind one calling convention.

Every provider takes a Request and returns a Result with the text and the
token counts the service reported. The cloud providers came from radioserver's
library/ai.py; Ollama (local, on this machine) is called over its HTTP API.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Callable

from ai_delegator import config

DEFAULT_MAX_TOKENS = 4096
CLOUD_TIMEOUT = 120    # seconds per request
LOCAL_TIMEOUT = 600    # a vision model on the local GPU can take minutes
CLIENT_RETRIES = 1


@dataclass
class Image:
    data: bytes
    media_type: str


@dataclass
class Request:
    messages: list[dict]                 # [{"role": "user"|"assistant", "content": str}]
    system: str | None = None
    images: list[Image] = field(default_factory=list)   # attached to the last user message
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float | None = None
    json_schema: dict | None = None      # ask for JSON matching this schema
    extra: dict = field(default_factory=dict)  # provider-specific request fields, passed through as-is


@dataclass
class Result:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    # Ollama's own timings, in ms
    load_ms: float | None = None
    prompt_eval_ms: float | None = None
    eval_ms: float | None = None


class ProviderError(Exception):
    pass


def _schema_instruction(schema: dict) -> str:
    return "\n\nRespond with only a JSON object matching this JSON schema:\n" + json.dumps(schema)


def _last_user_index(messages: list[dict]) -> int:
    for i in range(len(messages) - 1, -1, -1):
        if messages[i]["role"] == "user":
            return i
    raise ProviderError("The request has no user message")


# ---- OpenAI and the services with an OpenAI-compatible API ----

def _openai_compatible(base_url: str | None, conf_key: str, strict_schema: bool):
    def ask(req: Request, model: str) -> Result:
        from openai import OpenAI

        client = OpenAI(api_key=config.get("api", conf_key), base_url=base_url,
                        timeout=CLOUD_TIMEOUT, max_retries=CLIENT_RETRIES)
        messages = [{"role": m["role"], "content": m["content"]} for m in req.messages]
        kwargs = {}
        if req.json_schema is not None:
            if strict_schema:
                kwargs["response_format"] = {"type": "json_schema",
                                             "json_schema": {"name": "result", "schema": req.json_schema}}
            else:
                # DeepSeek, Groq and OpenRouter models don't all take a schema; ask in words
                kwargs["response_format"] = {"type": "json_object"}
                i = _last_user_index(messages)
                messages[i]["content"] += _schema_instruction(req.json_schema)
        if req.images:
            i = _last_user_index(messages)
            messages[i]["content"] = [{"type": "text", "text": messages[i]["content"]}] + [
                {"type": "image_url", "image_url": {
                    "url": f"data:{im.media_type};base64,{base64.standard_b64encode(im.data).decode()}"}}
                for im in req.images]
        if req.system:
            messages.insert(0, {"role": "system", "content": req.system})
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        response = client.chat.completions.create(
            model=model, messages=messages, max_tokens=req.max_tokens, **kwargs, **req.extra)
        if not response.choices:
            raise ProviderError(f"No answer returned: {getattr(response, 'error', response)}")
        usage = response.usage
        cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None) if usage else None
        return Result(
            text=(response.choices[0].message.content or "").strip(),
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            cache_read_tokens=cached,
        )
    return ask


# ---- Anthropic (Claude) ----

def _ask_claude(req: Request, model: str) -> Result:
    from anthropic import Anthropic

    client = Anthropic(api_key=config.get("api", "anthropic_key"), timeout=CLOUD_TIMEOUT,
                       max_retries=CLIENT_RETRIES)
    messages = [{"role": m["role"], "content": m["content"]} for m in req.messages]
    if req.images:
        i = _last_user_index(messages)
        messages[i]["content"] = [
            {"type": "image", "source": {"type": "base64", "media_type": im.media_type,
                                         "data": base64.standard_b64encode(im.data).decode()}}
            for im in req.images] + [{"type": "text", "text": messages[i]["content"]}]
    kwargs = {}
    if req.system:
        kwargs["system"] = req.system
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.json_schema is not None:
        kwargs["output_config"] = {"format": {"type": "json_schema", "schema": req.json_schema}}
    kwargs.update(req.extra)
    # Streaming avoids request timeouts on long answers; only the final message is used
    with client.messages.stream(model=model, max_tokens=req.max_tokens, messages=messages, **kwargs) as stream:
        message = stream.get_final_message()
    text = "".join(b.text for b in message.content if b.type == "text").strip()
    if message.stop_reason == "refusal":
        raise ProviderError("Claude declined to answer this request")
    return Result(
        text=text,
        input_tokens=message.usage.input_tokens + (message.usage.cache_read_input_tokens or 0)
        + (message.usage.cache_creation_input_tokens or 0),
        output_tokens=message.usage.output_tokens,
        cache_read_tokens=message.usage.cache_read_input_tokens,
    )


# ---- Google Gemini ----

def _ask_google(req: Request, model: str) -> Result:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.get("api", "google_ai_key"),
                          http_options=types.HttpOptions(timeout=CLOUD_TIMEOUT * 1000))
    last_user = _last_user_index(req.messages)
    contents = []
    for i, m in enumerate(req.messages):
        text = m["content"]
        if i == last_user and req.json_schema is not None:
            text += _schema_instruction(req.json_schema)
        parts = [types.Part.from_text(text=text)]
        if i == last_user:
            parts += [types.Part.from_bytes(data=im.data, mime_type=im.media_type) for im in req.images]
        contents.append(types.Content(role="model" if m["role"] == "assistant" else "user", parts=parts))
    cfg = {"max_output_tokens": req.max_tokens, **req.extra}
    if req.system:
        cfg["system_instruction"] = req.system
    if req.temperature is not None:
        cfg["temperature"] = req.temperature
    if req.json_schema is not None:
        cfg["response_mime_type"] = "application/json"
    response = client.models.generate_content(
        model=model, contents=contents, config=types.GenerateContentConfig(**cfg))
    usage = response.usage_metadata
    return Result(
        text=(response.text or "").strip(),
        input_tokens=getattr(usage, "prompt_token_count", None),
        output_tokens=getattr(usage, "candidates_token_count", None),
        cache_read_tokens=getattr(usage, "cached_content_token_count", None),
    )


# ---- Ollama (local) ----

def ollama_metrics(body: dict) -> dict:
    """Token counts and timings from a finished Ollama response (durations are in ns)."""
    ms = lambda k: round(body[k] / 1e6, 1) if body.get(k) is not None else None
    return {
        "input_tokens": body.get("prompt_eval_count"),
        "output_tokens": body.get("eval_count"),
        "load_ms": ms("load_duration"),
        "prompt_eval_ms": ms("prompt_eval_duration"),
        "eval_ms": ms("eval_duration"),
    }


def _ask_ollama(req: Request, model: str) -> Result:
    import httpx

    messages = [{"role": m["role"], "content": m["content"]} for m in req.messages]
    if req.images:
        messages[_last_user_index(messages)]["images"] = [
            base64.standard_b64encode(im.data).decode() for im in req.images]
    if req.system:
        messages.insert(0, {"role": "system", "content": req.system})
    options = {"num_predict": req.max_tokens}
    if req.temperature is not None:
        options["temperature"] = req.temperature
    extra = dict(req.extra)
    options.update(extra.pop("options", {}))
    body = {"model": model, "messages": messages, "stream": False, "options": options, **extra}
    if req.json_schema is not None:
        body["format"] = req.json_schema
    url = config.ollama_url()
    try:
        resp = httpx.post(f"{url}/api/chat", json=body, timeout=LOCAL_TIMEOUT)
    except httpx.HTTPError as e:
        raise ProviderError(f"Could not reach Ollama at {url}: {e}")
    if resp.status_code != 200:
        try:
            msg = resp.json().get("error") or resp.text
        except ValueError:
            msg = resp.text
        raise ProviderError(f"Ollama error {resp.status_code}: {msg[:300]}")
    data = resp.json()
    if data.get("done_reason") == "length":
        raise ProviderError(f"The answer was cut off at max_tokens ({req.max_tokens})")
    return Result(text=((data.get("message") or {}).get("content") or "").strip(), **ollama_metrics(data))


@dataclass
class Provider:
    name: str
    display: str
    conf_key: str | None        # key in the [api] section, or None if no key is needed
    default_model: str
    local: bool
    ask: Callable[[Request, str], Result]
    key_url: str = ""
    default_extra: dict = field(default_factory=dict)

    def configured(self) -> bool:
        return self.conf_key is None or bool(config.get("api", self.conf_key))


PROVIDERS: dict[str, Provider] = {p.name: p for p in [
    Provider("ollama", "Ollama (local)", None, "qwen3:8b", True, _ask_ollama),
    Provider("claude", "Claude", "anthropic_key", "claude-opus-5-5", False, _ask_claude,
             "https://console.anthropic.com/"),
    Provider("openai", "OpenAI", "openai_key", "gpt-4o-mini", False,
             _openai_compatible(None, "openai_key", strict_schema=True), "https://platform.openai.com/"),
    Provider("google", "Google Gemini", "google_ai_key", "gemini-2.0-flash", False, _ask_google,
             "https://aistudio.google.com/"),
    # deepseek-flash reasons before answering by default, which uses up max_tokens
    # and can return an empty reply
    Provider("deepseek", "DeepSeek", "deepseek_key", "deepseek-flash", False,
             _openai_compatible("https://api.deepseek.com", "deepseek_key", strict_schema=False),
             "https://platform.deepseek.com/", {"extra_body": {"thinking": {"type": "disabled"}}}),
    # gpt-oss is a reasoning model: its reasoning counts against max_tokens
    Provider("groq", "Groq", "groq_key", "openai/gpt-oss-120b", False,
             _openai_compatible("https://api.groq.com/openai/v1", "groq_key", strict_schema=False),
             "https://console.groq.com/", {"reasoning_effort": "low"}),
    Provider("openrouter", "OpenRouter", "openrouter_key", "meta-llama/llama-3.3-70b-instruct", False,
             _openai_compatible("https://openrouter.ai/api/v1", "openrouter_key", strict_schema=False),
             "https://openrouter.ai/"),
]}

# radioserver's ~/.radioserver.conf uses the same [api] key names
RADIOSERVER_CONF_KEYS = [p.conf_key for p in PROVIDERS.values() if p.conf_key]


def sniff_media_type(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    raise ProviderError("Unsupported image type; send JPEG, PNG, WebP or GIF")
