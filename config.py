from __future__ import annotations
import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Ensure .env is loaded from the script directory even when executed via Cron
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH)

class Config:
    BASE_DIR: Path = BASE_DIR
    # Zoho Books settings
    ZOHO_CLIENT_ID: str = os.getenv("ZOHO_CLIENT_ID", "")
    ZOHO_CLIENT_SECRET: str = os.getenv("ZOHO_CLIENT_SECRET", "")
    ZOHO_REFRESH_TOKEN: str = os.getenv("ZOHO_REFRESH_TOKEN", "")
    ZOHO_ORGANIZATION_ID: str = os.getenv("ZOHO_ORGANIZATION_ID", "")
    ZOHO_DOMAIN: str = os.getenv("ZOHO_DOMAIN", "com").strip().lower()

    @property
    def ZOHO_ACCOUNTS_URL(self) -> str:
        return f"https://accounts.zoho.{self.ZOHO_DOMAIN}"

    @property
    def ZOHO_BOOKS_API_URL(self) -> str:
        return f"https://www.zohoapis.{self.ZOHO_DOMAIN}/books/v3"

    # Plex settings
    PLEX_TOKEN: str = os.getenv("PLEX_TOKEN", "")
    PLEX_SERVER_NAME: str = os.getenv("PLEX_SERVER_NAME", "")
    # Raw libraries string from env
    _PLEX_LIBRARIES_RAW: str = os.getenv("PLEX_LIBRARIES", "")

    @property
    def PLEX_LIBRARIES(self) -> List[str]:
        if not self._PLEX_LIBRARIES_RAW or self._PLEX_LIBRARIES_RAW.strip().upper() == "ALL":
            return []
        return [lib.strip() for lib in self._PLEX_LIBRARIES_RAW.split(",") if lib.strip()]

    # Discord settings
    DISCORD_BOT_TOKEN: str = os.getenv("DISCORD_BOT_TOKEN", "")
    _DISCORD_ALLOWED_USERS_RAW: str = os.getenv("DISCORD_ALLOWED_USERS", "")
    DISCORD_GUILD_ID: str = os.getenv("DISCORD_GUILD_ID", "")
    DISCORD_NOTIFICATION_CHANNEL_ID: str = os.getenv("DISCORD_NOTIFICATION_CHANNEL_ID", "1552699204772696267")
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")

    @property
    def DISCORD_ALLOWED_USERS(self) -> List[int]:
        if not self._DISCORD_ALLOWED_USERS_RAW:
            return []
        ids = []
        for u_id in self._DISCORD_ALLOWED_USERS_RAW.split(","):
            u_id_clean = u_id.strip()
            if u_id_clean.isdigit():
                ids.append(int(u_id_clean))
        return ids

    # Business Rules
    OVERDUE_DAYS_THRESHOLD: int = int(os.getenv("OVERDUE_DAYS_THRESHOLD", "3"))

    # Logging
    LOG_DIR: Path = BASE_DIR / os.getenv("LOG_DIR", "logs")

    @classmethod
    def validate(cls) -> List[str]:
        """Validates that essential environment variables are set."""
        missing = []
        inst = cls()
        if not inst.ZOHO_CLIENT_ID:
            missing.append("ZOHO_CLIENT_ID")
        if not inst.ZOHO_CLIENT_SECRET:
            missing.append("ZOHO_CLIENT_SECRET")
        if not inst.ZOHO_REFRESH_TOKEN:
            missing.append("ZOHO_REFRESH_TOKEN")
        if not inst.ZOHO_ORGANIZATION_ID:
            missing.append("ZOHO_ORGANIZATION_ID")
        if not inst.PLEX_TOKEN:
            missing.append("PLEX_TOKEN")
        return missing

config = Config()
