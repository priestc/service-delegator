"""Settings live in ~/.service-delegator.conf (INI):

    [api]
    anthropic_key = sk-ant-...
    openai_key = sk-...

    [server]
    port = 5055
    ollama_url = http://127.0.0.1:11434
    db_path = ~/.local/share/service-delegator/delegator.db
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path

CONF_PATH = Path.home() / ".service-delegator.conf"
# Before the rename from ai-delegator; moved to the new names on first run
_OLD_CONF_PATH = Path.home() / ".ai-delegator.conf"
_OLD_DATA_DIR = Path.home() / ".local/share/ai-delegator"

DEFAULT_PORT = 5055
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_DB_PATH = "~/.local/share/service-delegator/delegator.db"


def migrate_old_names() -> None:
    """Move the config file and data directory from their ai-delegator names."""
    if _OLD_CONF_PATH.exists() and not CONF_PATH.exists():
        _OLD_CONF_PATH.rename(CONF_PATH)
    new_dir = Path(os.path.expanduser(DEFAULT_DB_PATH)).parent
    if _OLD_DATA_DIR.exists() and not new_dir.exists():
        _OLD_DATA_DIR.rename(new_dir)


def _read() -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    config.read(CONF_PATH)
    return config


def get(section: str, key: str, fallback: str = "") -> str:
    return _read().get(section, key, fallback=fallback)


def set_value(section: str, key: str, value: str) -> None:
    config = _read()
    if not config.has_section(section):
        config.add_section(section)
    config.set(section, key, value)
    # The file holds API keys: keep it readable only by its owner
    fd = os.open(CONF_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        config.write(f)


def port() -> int:
    return int(get("server", "port", str(DEFAULT_PORT)))


def ollama_url() -> str:
    return get("server", "ollama_url", DEFAULT_OLLAMA_URL).rstrip("/")


def db_path() -> str:
    p = os.path.expanduser(get("server", "db_path", DEFAULT_DB_PATH))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p
