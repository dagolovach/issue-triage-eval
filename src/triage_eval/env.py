"""Load a .env file into os.environ. Zero dependencies.

Called automatically by fetch / run (and anything that needs keys). Existing
environment variables always win over .env, so `export FOO=bar` still overrides.
Uses python-dotenv if it happens to be installed, else a tiny built-in parser.
"""
from __future__ import annotations
import os
from pathlib import Path

# repo root = two levels up from this file (src/triage_eval/env.py)
_ROOT = Path(__file__).resolve().parents[2]


def load_env(path: str | os.PathLike | None = None) -> None:
    env_path = Path(path) if path else _ROOT / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # optional
        load_dotenv(env_path, override=False)
        return
    except ImportError:
        pass
    # fallback parser: KEY=VALUE, ignores blanks/comments, strips quotes
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:  # don't clobber a real env var
            os.environ[key] = val
