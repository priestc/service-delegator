# AI Delegator — Project Notes

Runs on **tank2** (`ssh tank2`), next to Ollama and the GPU it monitors, as
the user systemd service `ai-delegator.service` (`systemctl --user`, no sudo) on port 5055. Database: `~/.local/share/ai-delegator/delegator.db`.
API keys: `~/.ai-delegator.conf` (mode 600; never commit or print them).

Deploy after a commit:

```
pipx install git+https://github.com/priestc/AI-delegator.git@master --force; systemctl --user restart ai-delegator.service
```

When the user mentions testing something, commit, push and deploy first.

Logs: `journalctl --user -u ai-delegator.service`.

## Error handling principle

Never silently swallow errors. Failed provider calls are logged with their
error and shown in the UI; API errors return a message (and the notes from
each provider tried); fetch failures on the pages show an error banner.
