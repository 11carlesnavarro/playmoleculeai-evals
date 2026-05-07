"""Cost ceiling enforcement.

The runner consults a single :class:`Budget` per run. ``charge`` is called
after each rollout, ``check`` is called before the next one. When the
ceiling is hit, ``check`` raises :class:`BudgetExceededError`, which the
executor catches to write a partial summary and exit with code 2.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pmai_evals.errors import BudgetExceededError
from pmai_evals.schemas import CostCharge, CostJournal

logger = logging.getLogger(__name__)


class Budget:
    """Mutable cost tracker with persisted journal."""

    def __init__(self, max_cost_usd: float, journal_path: Path):
        if max_cost_usd <= 0:
            raise ValueError("max_cost_usd must be positive")
        self._journal = CostJournal(max_cost_usd=max_cost_usd)
        self._journal_path = journal_path
        self._save()

    @property
    def total_cost_usd(self) -> float:
        return self._journal.total_cost_usd

    @property
    def max_cost_usd(self) -> float:
        return self._journal.max_cost_usd

    @property
    def remaining_usd(self) -> float:
        return max(self._journal.max_cost_usd - self._journal.total_cost_usd, 0.0)

    def check(self) -> None:
        """Raise if we're already over budget. Call before each rollout."""
        if self._journal.total_cost_usd >= self._journal.max_cost_usd:
            raise BudgetExceededError(
                f"budget exhausted: ${self._journal.total_cost_usd:.4f} "
                f">= ${self._journal.max_cost_usd:.4f}"
            )

    def charge(
        self,
        *,
        case_id: str,
        model: str,
        seed: int,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int,
        cost_usd: float,
    ) -> CostCharge:
        """Add one rollout's cost to the running total and persist.

        ``cost_usd`` must already be priced per-API-call (so each request gets
        the correct tier); see :func:`pmai_evals.trace.parse_trace`.
        """
        charge = CostCharge(
            case_id=case_id,
            model=model,
            seed=seed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost_usd,
        )
        self._journal.charges.append(charge)
        self._journal.total_cost_usd = round(self._journal.total_cost_usd + cost_usd, 6)
        self._save()
        logger.info(
            "charged %s/%s seed=%d cost=$%.4f total=$%.4f / $%.2f",
            case_id, model, seed, cost_usd,
            self._journal.total_cost_usd, self._journal.max_cost_usd,
        )
        return charge

    def snapshot(self) -> CostJournal:
        return self._journal.model_copy(deep=True)

    def _save(self) -> None:
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        self._journal_path.write_text(
            self._journal.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
