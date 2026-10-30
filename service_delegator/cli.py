"""service-delegator command line."""
from __future__ import annotations

import argparse
import configparser
import sys
from pathlib import Path

from service_delegator import config
from service_delegator.providers import PROVIDERS


def _set_key(args) -> int:
    p = PROVIDERS.get(args.provider)
    if p is None or p.conf_key is None:
        names = ", ".join(n for n, x in PROVIDERS.items() if x.conf_key)
        print(f"Unknown provider {args.provider!r}; one that takes a key: {names}", file=sys.stderr)
        return 1
    config.set_value("api", p.conf_key, args.key)
    print(f"{p.display} key saved to {config.CONF_PATH}")
    return 0


def _import_radioserver(args) -> int:
    src = Path(args.path).expanduser()
    rs = configparser.ConfigParser()
    if not rs.read(src):
        print(f"Could not read {src}", file=sys.stderr)
        return 1
    copied = []
    for p in PROVIDERS.values():
        if p.conf_key and rs.get("api", p.conf_key, fallback=""):
            config.set_value("api", p.conf_key, rs.get("api", p.conf_key))
            copied.append(p.display)
    print(f"Copied keys for: {', '.join(copied) or 'nothing (no keys found)'}")
    return 0


def _import_latency(args) -> int:
    """Rows exported from radioserver's LookupLatency table (JSON list of
    {service, kind, title, artist, seconds, requests, ok, result, created_at})
    become calls with via='imported'. Each row was one whole lookup, which for
    MusicBrainz and Discogs could be several HTTP requests."""
    import datetime
    import json

    from service_delegator import db

    db.init()
    rows = json.loads(Path(args.file).read_text())
    names = {"MusicBrainz": "musicbrainz", "Discogs": "discogs"}
    conn = db.connect()
    try:
        if conn.execute("SELECT 1 FROM calls WHERE via='imported' LIMIT 1").fetchone():
            print("radioserver's timings were already imported", file=sys.stderr)
            return 1
        for r in rows:
            when = datetime.datetime.fromisoformat(r["created_at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            database = r["kind"] == "database"
            conn.execute(
                "INSERT INTO calls (started_at, project, task, provider, local, via, kind, status, error, duration_ms, "
                "prompt_preview, response_preview, endpoint) VALUES (?,?,?,?,0,'imported',?,?,?,?,?,?,?)",
                (when, "radioserver", "song-year", names.get(r["service"], r["service"]),
                 "api" if database else "ai", "ok" if r["ok"] else "error", None if r["ok"] else r["result"],
                 round(r["seconds"] * 1000, 1), f"{r['title']} \u2014 {r['artist']} ({r['kind']})",
                 r["result"] if r["ok"] else None,
                 f"lookup ({r['requests']} requests)" if database and r.get("requests") else None),
            )
        conn.commit()
    finally:
        conn.close()
    print(f"Imported {len(rows)} timings from radioserver")
    return 0


def _providers(args) -> int:
    for p in PROVIDERS.values():
        state = "local" if p.local else ("key set" if p.configured() else "no key")
        print(f"{p.name:11} {state:8} default model {p.default_model}")
    return 0


def _ask(args) -> int:
    from service_delegator.client import DelegatorError, ask

    try:
        a = ask(args.task, args.prompt, project=args.project, provider=args.provider, model=args.model,
                max_tokens=args.max_tokens, url=args.url)
    except DelegatorError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(a["text"])
    print(f"-- {a['provider']} {a['model']}, {a['duration_ms']:.0f} ms, "
          f"{a['input_tokens']} in / {a['output_tokens']} out tokens", file=sys.stderr)
    for n in a["notes"]:
        print(f"-- {n}", file=sys.stderr)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="service-delegator", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Run the web server and API")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=None, help=f"default {config.DEFAULT_PORT} or [server] port")

    s = sub.add_parser("set-key", help="Save a provider's API key")
    s.add_argument("provider")
    s.add_argument("key")

    s = sub.add_parser("import-radioserver-keys", help="Copy API keys from radioserver's config")
    s.add_argument("--path", default="~/.radioserver.conf")

    s = sub.add_parser("import-radioserver-latency", help="Import radioserver's lookup timings (JSON export)")
    s.add_argument("file")

    sub.add_parser("providers", help="List providers and whether their keys are set")

    s = sub.add_parser("ask", help="Send a prompt through a running server")
    s.add_argument("task")
    s.add_argument("prompt")
    s.add_argument("--project", default="cli")
    s.add_argument("--provider")
    s.add_argument("--model")
    s.add_argument("--max-tokens", type=int)
    s.add_argument("--url")

    args = parser.parse_args()
    config.migrate_old_names()
    if args.cmd == "serve":
        from service_delegator import web
        web.run(args.host, args.port or config.port())
        return
    sys.exit({"set-key": _set_key, "import-radioserver-keys": _import_radioserver,
              "import-radioserver-latency": _import_latency, "providers": _providers, "ask": _ask}[args.cmd](args))


if __name__ == "__main__":
    main()
