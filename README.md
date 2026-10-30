# Service Delegator

One place for all my projects to send AI prompts and web API requests, so
every outside service they depend on is logged in one place.

**AI** — each kind of job (a
**task**, e.g. `receipt-reader` or `song-year`) is routed to a provider
chosen on the web page, so a task can be moved from Claude to Groq to a local
Ollama model without touching the project. Every call is logged: duration,
tokens, errors, and for local Ollama calls the GPU temperature, power and fan
speed while it ran.

Providers: Ollama (local), Claude, OpenAI, Google Gemini, DeepSeek, Groq,
OpenRouter. The cloud provider code came from radioserver's `library/ai.py`.

## Running

```
pipx install git+https://github.com/priestc/service-delegator.git
service-delegator import-radioserver-keys      # or: service-delegator set-key claude sk-ant-...
service-delegator serve                        # http://<host>:5055
```

`service-delegator.service` runs it as a systemd user service (instructions at the top of the file).

## Using it from a project

**Through the API** — routed by task, any provider:

```python
from service_delegator.client import ask   # stdlib only; can also be copied into a project

answer = ask("song-year", "What year was 'Yesterday' by The Beatles released? Reply with just the year.",
             project="radioserver", max_tokens=20)
answer["text"]       # "1965"
answer["provider"]   # whichever provider the task is set to
```

Or plain HTTP: `POST /api/ask` with JSON `{"task", "project", "prompt" | "messages",
"system", "images" (base64), "max_tokens", "temperature", "json_schema", "timeout"}`.
A task used for the first time is created with the `default` task's providers.

**As an Ollama stand-in** — no code changes: point the project's Ollama URL at
`http://<host>:5055/ollama/<project-name>`. `/api/chat` and `/api/generate` are
logged with GPU readings; everything else passes straight through. Add an
`X-Task` header to name the task.

**Web APIs** — every other service my projects call (MusicBrainz, Discogs,
Google Places, Ecobee, Apple Push, YouTube, Crossref, OpenAlex, Internet
Archive, ...; the list is in `service_delegator/services.py`). A project sends
its requests to `http://<host>:5055/proxy/<project>/<service>/<path>` instead
of the service's base URL. They're forwarded unchanged, with the project's own
API key, and each one is logged with its endpoint, HTTP status, duration and
size. Add a service by adding a line to `services.py`.

## Pages

- `/` — calls, errors, time (avg, median, 95th percentile), tokens and GPU peaks by model and project, and recent calls
- `/calls/<id>` — one call: prompt, response, timings, and a GPU/CPU chart for local calls
- `/tasks` — which providers handle each task, in fallback order
- `/services` — AI providers (key status, test button) and web APIs (calls, errors, time, proxy URL)
