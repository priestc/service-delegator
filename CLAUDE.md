# AI Delegator — Project Notes

Runs on **tank2** (`ssh tank2`), next to Ollama and the GPU it monitors, as
`ai-delegator.service` on port 5055. Database: `~/.local/share/ai-delegator/delegator.db`.
API keys: `~/.ai-delegator.conf` (mode 600; never commit or print them).

Deploy after a commit:

```
pipx install git+https://github.com/priestc/AI-delegator.git@master --force; sudo -n systemctl restart ai-delegator.service
```

When the user mentions testing something, commit, push and deploy first.

## Error handling principle

Never silently swallow errors. Failed provider calls are logged with their
error and shown in the UI; API errors return a message (and the notes from
each provider tried); fetch failures on the pages show an error banner.
