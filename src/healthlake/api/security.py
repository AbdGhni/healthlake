"""API keys and signed cursors.

Keys: the server stores only SHA-256 hashes (HEALTHLAKE_API_KEYS_FILE, JSON list of
{"key_id", "sha256", "scopes"}). A presented key is hashed and compared to every stored hash with
hmac.compare_digest, always iterating the full list (no early exit on a match).
Scopes: "read" (analytics) and "ops" (quality, pipeline runs, releases, metrics).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from healthlake.config import ConfigError, secret

SCOPES = {"read", "ops"}


@dataclass(frozen=True)
class ApiKey:
    key_id: str
    sha256: bytes
    scopes: frozenset[str]


@lru_cache(maxsize=1)
def load_keys() -> tuple[ApiKey, ...]:
    path = os.environ.get("HEALTHLAKE_API_KEYS_FILE")
    if not path:
        raise ConfigError("HEALTHLAKE_API_KEYS_FILE is not set")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    keys = []
    for item in data:
        scopes = frozenset(item["scopes"])
        if not scopes <= SCOPES or len(bytes.fromhex(item["sha256"])) != 32:
            raise ConfigError(f"invalid API key entry {item.get('key_id')}")
        keys.append(ApiKey(item["key_id"], bytes.fromhex(item["sha256"]), scopes))
    if not keys:
        raise ConfigError("no API key configured")
    return tuple(keys)


def authenticate(presented: str | None) -> ApiKey | None:
    if not presented or len(presented) > 256:
        return None
    digest = hashlib.sha256(presented.encode("utf-8")).digest()
    found: ApiKey | None = None
    for k in load_keys():
        if hmac.compare_digest(digest, k.sha256) and found is None:
            found = k
    return found


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def _cursor_secret() -> bytes:
    value = secret("HEALTHLAKE_API_CURSOR_SECRET")
    assert value is not None
    if len(value) < 32:
        raise ConfigError("cursor secret must be at least 32 characters")
    return value.encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class CursorError(ValueError):
    pass


def encode_cursor(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_cursor_secret(), body, hashlib.sha256).digest()
    return f"{_b64(body)}.{_b64(sig)}"


def decode_cursor(token: str) -> dict[str, Any]:
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body, sig = _unb64(body_b64), _unb64(sig_b64)
    except ValueError:
        raise CursorError("malformed cursor") from None
    expected = hmac.new(_cursor_secret(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        raise CursorError("invalid cursor signature")
    data: dict[str, Any] = json.loads(body)
    return data


DEFAULT_CLIENTS = {"dashboard": ["read", "ops"], "analyst": ["read"], "operator": ["ops"]}


def generate_keys(hashed_out: Path, plain_out: Path, clients: dict[str, list[str]] | None = None) -> list[str]:
    """Create random keys. The API only ever sees the hashed file; plain keys go to a 0600 file for the operator."""
    import secrets as _secrets

    clients = clients or DEFAULT_CLIENTS
    plain: dict[str, str] = {}
    hashed = []
    for key_id, scopes in clients.items():
        raw = f"hl_{key_id}_{_secrets.token_urlsafe(32)}"
        plain[key_id] = raw
        hashed.append({"key_id": key_id, "sha256": hash_key(raw), "scopes": sorted(scopes)})
    for path, content in ((hashed_out, json.dumps(hashed, indent=2)), (plain_out, json.dumps(plain, indent=2))):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content + "\n")
    return sorted(clients)
