from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    model_provider: str = "openai"     # openai | ollama
    model_name: str = ""
    base_url: str | None = None        # OpenAI-compatible free endpoints
    api_key: str | None = None
    docker_image: str = "python:3.12-slim"

    class Config:
        env_file = ".env"
        extra = "allow"