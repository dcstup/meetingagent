from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Recall.ai
    recall_api_key: str
    recall_region: str = "us-east-1"

    # Anthropic
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-20250514"

    # Composio
    composio_api_key: str
    composio_user_id: str = "default"

    # Server
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8000
    webhook_base_url: str = ""

    # Agent behavior
    transcript_buffer_max_entries: int = 50
    agent_trigger_interval_seconds: float = 5.0
    bot_name: str = "Meeting Assistant"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
