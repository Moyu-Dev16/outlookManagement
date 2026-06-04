from functools import lru_cache
from pathlib import Path
import os

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


if load_dotenv:
    load_dotenv()


class Settings:
    microsoft_client_id: str = os.getenv("MS_CLIENT_ID", "")
    microsoft_client_secret: str = os.getenv("MS_CLIENT_SECRET", "")
    microsoft_redirect_uri: str = os.getenv(
        "MS_REDIRECT_URI", "http://localhost:8000/api/oauth/microsoft/callback"
    )
    app_base_url: str = os.getenv("APP_BASE_URL", "http://localhost:5173")
    database_path: Path = Path(
        os.getenv("DATABASE_PATH", "./data/outlook_manager.sqlite3")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
