"""SQLite storage: every call made through the delegator, GPU samples taken
during local (Ollama) calls, and the task -> provider routing."""
from __future__ import annotations

import json
import sqlite3

from ai_delegator import config


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init() -> None:
    conn = connect()
    try:
        # One row per prompt sent to a provider. A fallback chain that tries
        # three providers makes three rows. status is 'running', 'ok' or 'error';
        # a 'running' row whose process died stays that way (shown as unfinished).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS calls (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at         TEXT NOT NULL,
                project            TEXT,
                task               TEXT,
                provider           TEXT NOT NULL,
                model              TEXT,
                local              INTEGER NOT NULL,   -- 1 for Ollama on this machine
                via                TEXT NOT NULL,      -- 'ask' (/api/ask) or 'ollama-proxy'
                status             TEXT NOT NULL,
                error              TEXT,
                duration_ms        REAL,
                input_tokens       INTEGER,
                output_tokens      INTEGER,
                cache_read_tokens  INTEGER,
                n_images           INTEGER NOT NULL DEFAULT 0,
                prompt_preview     TEXT,
                response_preview   TEXT,
                -- Ollama's own timings (ms): model load, reading the prompt, generating
                load_ms            REAL,
                prompt_eval_ms     REAL,
                eval_ms            REAL,
                -- GPU/CPU readings during a local call (summary of gpu_samples)
                gpu_peak_junction  REAL,
                gpu_avg_junction   REAL,
                gpu_peak_edge      REAL,
                gpu_peak_mem       REAL,
                gpu_peak_power     REAL,
                gpu_avg_power      REAL,
                gpu_peak_fan       REAL,
                cpu_peak           REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS calls_started ON calls (started_at)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS gpu_samples (
                call_id  INTEGER NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
                t        REAL NOT NULL,     -- seconds since the call started
                edge     REAL,
                junction REAL,
                mem      REAL,
                power    REAL,
                sclk     REAL,
                fan_rpm  REAL,
                cpu      REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS gpu_samples_call ON gpu_samples (call_id)")
        # routes: JSON list of {"provider", "model"} tried in order until one
        # answers. options: JSON passed to every provider (e.g. max_tokens).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                name        TEXT PRIMARY KEY,
                description TEXT,
                routes      TEXT NOT NULL,
                options     TEXT NOT NULL DEFAULT '{}',
                updated_at  TEXT NOT NULL
            )
        """)
        if conn.execute("SELECT 1 FROM tasks WHERE name='default'").fetchone() is None:
            conn.execute(
                "INSERT INTO tasks (name, description, routes, updated_at) VALUES ('default', ?, ?, datetime('now','localtime'))",
                ("Used for any task that hasn't been set up yet",
                 json.dumps([{"provider": "ollama", "model": "qwen3:8b"}])),
            )
        conn.commit()
    finally:
        conn.close()
