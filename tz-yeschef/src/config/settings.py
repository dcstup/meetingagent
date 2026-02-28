from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://localhost/yeschef"

    @model_validator(mode="after")
    def _fix_db_url(self):
        url = self.database_url
        if url.startswith("postgresql://"):
            self.database_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            self.database_url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        return self
    recall_api_key: str = ""
    composio_api_key: str = ""
    deepinfra_api_key: str = ""
    cerebras_api_key: str = ""
    app_public_url: str = "http://localhost:8000"
    bot_name: str = "YesChef"
    webhook_secret: str = ""  # auto-generated if empty
    overlay_token: str = ""   # auto-generated if empty

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
