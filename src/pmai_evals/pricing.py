"""Loader for the static model registry in ``pricing.yaml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ruamel.yaml import YAML

from pmai_evals.errors import ConfigError
from pmai_evals.schemas import ModelEntry, ModelRegistry

_PRICING_PATH = Path(__file__).parent / "pricing.yaml"


@lru_cache(maxsize=1)
def load_registry() -> ModelRegistry:
    """Parse ``pricing.yaml`` once per process."""

    yaml = YAML(typ="safe")
    try:
        data = yaml.load(_PRICING_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"pricing.yaml not found at {_PRICING_PATH}") from exc
    if not isinstance(data, dict) or "models" not in data:
        raise ConfigError("pricing.yaml must contain a top-level 'models' list")
    return ModelRegistry.model_validate(data)


def cost_for_usage(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """Compute the USD cost of one rollout from token counts.

    Cached tokens are billed at the cached input rate (and excluded from the
    full input rate). Unknown models charge zero — flagged via warning at
    the call site, never silently.
    """

    registry = load_registry()
    try:
        entry: ModelEntry = registry.get(model_id)
    except KeyError:
        return 0.0

    fresh_input = max(input_tokens - cached_tokens, 0)
    return (
        fresh_input * entry.input_per_mtok_usd / 1_000_000.0
        + cached_tokens * entry.cached_input_per_mtok_usd / 1_000_000.0
        + output_tokens * entry.output_per_mtok_usd / 1_000_000.0
    )


def supports_vision(model_id: str) -> bool:
    try:
        return load_registry().get(model_id).supports_vision
    except KeyError:
        return False
