"""Fault injection for crash tests. Inactive unless HEALTHLAKE_CRASH_AT names the crash point."""

from __future__ import annotations

import os


class InjectedCrashError(RuntimeError):
    """Raised at a configured crash point to simulate a process dying."""


def crashpoint(name: str) -> None:
    target = os.environ.get("HEALTHLAKE_CRASH_AT")
    if target and target == name:
        if os.environ.get("HEALTHLAKE_CRASH_MODE") == "exit":
            os._exit(137)  # hard kill: no cleanup, no rollback handlers
        raise InjectedCrashError(f"injected crash at {name}")
