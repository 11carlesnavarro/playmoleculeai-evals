"""Typed exceptions raised across the harness.

Catching bare ``Exception`` is forbidden everywhere except the per-case
isolation barrier in ``runner.executor``.
"""

from __future__ import annotations


class PMAIEvalsError(Exception):
    """Base class for all harness errors."""


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
    """No trace was returned for the given chat id."""


class TraceParseError(PMAIEvalsError):
    """A trace payload could not be parsed."""


class BudgetExceededError(PMAIEvalsError):
    """The current run exhausted its cost ceiling."""


class JudgeError(PMAIEvalsError):
    """The LLM judge could not produce a valid grade."""


class HarnessError(PMAIEvalsError):
    """Unrecoverable harness-level failure (exit code 3)."""
