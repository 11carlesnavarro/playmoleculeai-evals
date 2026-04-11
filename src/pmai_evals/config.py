"""Process-wide settings loaded from environment + .env."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All harness configuration. Constructed once at the CLI entrypoint."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- playmolecule connection ---
    pm_frontend_url: str = "http://localhost:5173"
    pm_backend_url: str = "http://localhost:8000"
    pm_agent_url: str = "http://localhost:8102"

    # --- auth ---
    pm_email: str | None = None
    pm_password: str | None = None
    pm_user_bucket: str = "/shared2/pmai/pmbackend/public-projects"
    pm_project: str = "pmai-evals"

    # --- judge & provider keys ---
    pmai_evals_judge_model: str = "claude-sonnet-4-6"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None

    # --- run defaults ---
    pmai_evals_max_cost_usd: float = 10.0
    pmai_evals_results_dir: Path = Path("./runs")
    pmai_evals_headless: bool = True
    pmai_evals_log_level: str = "INFO"
    pmai_evals_auth_state: Path = Path("playwright/.auth/storage_state.json")

    # --- timeouts ---
    pmai_evals_default_timeout_s: int = Field(default=300)
    pmai_evals_browser_navigation_timeout_s: int = Field(default=60)

    @property
    def auth_state_path(self) -> Path:
        return self.pmai_evals_auth_state

    @property
    def results_dir(self) -> Path:
        return self.pmai_evals_results_dir
