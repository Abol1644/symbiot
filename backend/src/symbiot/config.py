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
    docker_image: str = "python:3.12-slim"

    model_config = SettingsConfigDict(env_file=".env", extra="allow", populate_by_name=True)
