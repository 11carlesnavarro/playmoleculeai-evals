"""Typed exceptions raised across the harness.

Catching bare ``Exception`` is forbidden everywhere except the per-case
isolation barrier in ``runner.executor`` (spec §6.3).
"""

from __future__ import annotations


class PMAIEvalsError(Exception):
    """Base class. Anything we raise should subclass this."""


class ConfigError(PMAIEvalsError):
    """Bad configuration: missing env, invalid YAML, unknown assertion type."""


class AssertionConfigError(ConfigError):
    """An assertion declared in cases.yaml is malformed or unknown."""


class EvalSetLoadError(ConfigError):
    """An eval set on disk could not be parsed."""


class BrowserError(PMAIEvalsError):
    """Anything wrong with the Playwright session."""


class AuthError(BrowserError):
    """Login failed or storage state is unusable."""


class ChatTimeoutError(BrowserError):
    """A chat rollout did not finish within the configured timeout."""


class TraceNotFoundError(PMAIEvalsError):
    """No row found in SQLite for the given chat id."""


class TraceParseError(PMAIEvalsError):
    """A row exists but the JSON payload could not be parsed."""


class BudgetExceededError(PMAIEvalsError):
    """The current run exhausted its cost ceiling."""


class JudgeError(PMAIEvalsError):
    """The LLM judge could not produce a valid grade."""


class RunFailedError(PMAIEvalsError):
    """A single case failed in a way that should be recorded as ``status: failed``."""


class HarnessError(PMAIEvalsError):
    """Unrecoverable harness-level failure (exit code 3)."""
