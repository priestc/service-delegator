# AI Delegator

One place for all my projects to send AI prompts. Each kind of job (a
**task**, e.g. `receipt-reader` or `song-year`) is routed to a provider
chosen on the web page, so a task can be moved from Claude to Groq to a local
Ollama model without touching the project. Every call is logged: duration,
tokens, errors, and for local Ollama calls the GPU temperature, power and fan
speed while it ran.

Providers: Ollama (local), Claude, OpenAI, Google Gemini, DeepSeek, Groq,
OpenRouter. The cloud provider code came from radioserver's `library/ai.py`.

## Running

```
pipx install git+https://github.com/priestc/AI-delegator.git
ai-delegator import-radioserver-keys      # or: ai-delegator set-key claude sk-ant-...
ai-delegator serve                        # http://<host>:5055
```

`ai-delegator.service` runs it under systemd.

## Using it from a project

**Through the API** — routed by task, any provider:

```python
from ai_delegator.client import ask   # stdlib only; can also be copied into a project

answer = ask("song-year", "What year was 'Yesterday' by The Beatles released? Reply with just the year.",
             project="radioserver", max_tokens=20)
answer["text"]       # "1965"
answer["provider"]   # whichever provider the task is set to
```

Or plain HTTP: `POST /api/ask` with JSON `{"task", "project", "prompt" | "messages",
"system", "images" (base64), "max_tokens", "temperature", "json_schema"}`.
A task used for the first time is created with the `default` task's providers.

**As an Ollama stand-in** — no code changes: point the project's Ollama URL at
`http://<host>:5055/ollama/<project-name>`. `/api/chat` and `/api/generate` are
logged with GPU readings; everything else passes straight through. Add an
`X-Task` header to name the task.

## Pages

- `/` — calls, errors, time (avg, median, 95th percentile), tokens and GPU peaks by model and project, and recent calls
- `/calls/<id>` — one call: prompt, response, timings, and a GPU/CPU chart for local calls
- `/tasks` — which providers handle each task, in fallback order
- `/providers` — API key status and a test button for each provider
