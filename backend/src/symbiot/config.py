from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_provider: str = "openai"
    model_name: str = ""
    base_url: str | None = None
    api_key: str | None = None
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openrouter_api_key: str | None = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    opencode_api_key: str | None = Field(default=None, validation_alias="OPENCODE_API_KEY")
    generic_api_key: str | None = Field(default=None, validation_alias="GENERIC_OPENAI_API_KEY")
    fallback_chain: str = ""
    run_timeout_minutes: int = 30
    workspace_root: Path = Field(
        default_factory=lambda: Path.home() / ".symbiot" / "workspace",
        validation_alias="SYMBIOT_WORKSPACE_ROOT",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="allow", populate_by_name=True)


def get_workspace_root(settings: Settings | None = None) -> Path:
    """Single source of truth for where agent workspaces live.

    Defaults to ``~/.symbiot/workspace``; override with ``SYMBIOT_WORKSPACE_ROOT``.
    Always returns an absolute, expanded path (resolved where possible).
    """

    root = Path((settings or Settings()).workspace_root).expanduser()
    try:
        return root.resolve()
    except OSError:
        return root.absolute()
