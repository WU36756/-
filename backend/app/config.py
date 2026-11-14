"""Runtime configuration (APP_* environment variables)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    llm_provider: str = "mock"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-flash"
    temperature: float = 0.2
    max_tokens: int = 3200
    reasoning_effort: str = "low"
    timeout_seconds: float = 90.0
    tool_timeout_seconds: float = 30.0
    max_tool_steps: int = 3
    max_snippet_chars: int = 700

    # NCBI E-utilities etiquette (an API key raises the rate limit to 10 req/s).
    ncbi_tool: str = "health-agent-platform"
    ncbi_email: str = ""
    ncbi_api_key: str = ""

    custom_api_base: str = ""
    custom_api_model: str = ""
    custom_api_key: str = ""
    demo_reset_enabled: bool = True
    allow_private_custom: bool = False
    rate_limit_per_minute: int = 60
    access_code: str = ""
    secret_key: str = ""
    cookie_secure: bool = False


settings = Settings()
