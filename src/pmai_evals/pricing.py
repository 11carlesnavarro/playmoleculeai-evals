"""Loader for the static model registry in ``pricing.yaml``."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from ruamel.yaml import YAML

from pmai_evals.errors import ConfigError
from pmai_evals.schemas import ModelEntry, ModelRegistry

_PRICING_PATH = Path(__file__).parent / "pricing.yaml"
_DATE_SUFFIX_RE = re.compile(r"[-_]\d{4}-\d{2}-\d{2}$")


def normalize_model_id(model_id: str) -> str:
    """Strip the trailing ``-YYYY-MM-DD`` snapshot suffix providers tack on."""

    return _DATE_SUFFIX_RE.sub("", model_id.strip())


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

    Cached tokens are a subset of ``input_tokens`` and are billed at the
    cached rate; the rest is billed at the fresh-input rate. The price tier
    is selected by total ``input_tokens`` against each tier's
    ``max_prompt_tokens``. Unknown models return 0.0.
    """

    registry = load_registry()
    try:
        entry: ModelEntry = registry.get(normalize_model_id(model_id))
    except KeyError:
        return 0.0

    cached_tokens = min(max(cached_tokens, 0), input_tokens)
    fresh_input = input_tokens - cached_tokens
    tier = entry.select_tier(input_tokens)
    return (
        fresh_input * tier.input_per_mtok_usd
        + cached_tokens * tier.cached_input_per_mtok_usd
        + output_tokens * tier.output_per_mtok_usd
    ) / 1_000_000.0


def supports_vision(model_id: str) -> bool:
    try:
        return load_registry().get(normalize_model_id(model_id)).supports_vision
    except KeyError:
        return False
