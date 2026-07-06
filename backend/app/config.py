"""
Environment-driven configuration. Load once at import time via pydantic-settings
so every module gets validated, typed config instead of scattered os.getenv calls.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-max"
    qwen_embedding_model: str = "text-embedding-v3"

    database_url: str = ""  # empty -> falls back to in-memory store, see store.py

    enable_hitl_gate: bool = False
    max_decision_text_length: int = 2000
    agent_temperature: float = 0.5
    
    max_documents_per_decision: int = 3
    max_document_size_bytes: int = 5 * 1024 * 1024
    max_extracted_chars_per_document: int = 3000
    csv_sample_rows: int = 10
    max_csv_columns: int = 200
    max_csv_rows: int = 100_000

    # Alibaba Cloud OSS — original uploaded file storage, see object_store.py.
    # Falls back to LocalFilesystemObjectStore when unset (local dev/testing).
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""
    oss_endpoint: str = "https://oss-ap-southeast-1.aliyuncs.com"
    oss_bucket_name: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    cors_allowed_origins: str = "http://localhost:5173"

    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_app_token: str = ""  # for Socket Mode, used in local dev

    # Clerk auth -- see auth.py. clerk_issuer is your Clerk Frontend API URL,
    # e.g. "https://your-app-name.clerk.accounts.dev" (find it in the Clerk
    # dashboard under API Keys, or decode any session JWT's `iss` claim).
    clerk_issuer: str = ""

    # Credit-protection rate limits -- see rate_limit.py. Defaults are
    # deliberately small (a handful of tries per person, a few dozen total
    # per day) since these gate real Qwen API spend, not just noise control.
    max_decisions_per_user_per_day: int = 5
    max_total_decisions_per_day: int = 30
    # Comma-separated Clerk user_ids that bypass both caps above -- put your
    # own account here while testing so you're not eating the same budget
    # you're protecting from everyone else.
    unlimited_user_ids: str = ""

    @property
    def unlimited_user_ids_set(self) -> set[str]:
        return {u.strip() for u in self.unlimited_user_ids.split(",") if u.strip()}

settings = Settings()
