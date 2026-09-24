import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
from config import config
from logger_service import logger

DATA_DIR = config.BASE_DIR / "data"
GRANTS_FILE = DATA_DIR / "grants.json"

class GrantService:
    def __init__(self, file_path: Path = GRANTS_FILE):
        self.file_path = file_path
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            initial_data = {
                "temporary_passes": {},
                "permanent_passes": {}
            }
            self._save_data(initial_data)

    def _load_data(self) -> Dict[str, Any]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read grants data file {self.file_path}: {e}")
            return {"temporary_passes": {}, "permanent_passes": {}}

    def _save_data(self, data: Dict[str, Any]):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to write grants data file {self.file_path}: {e}")

    def add_temporary_pass(
        self,
        email: str,
        customer_name: str = "",
        customer_id: str = "",
        days: int = 2,
        reference_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Adds a temporary pass valid for `days` days (default: 2 days, or 3 days if granted on Friday)."""
        email_clean = email.strip().lower()
        now = reference_time if reference_time is not None else datetime.now()

        # If granted on Friday (weekday == 4) and default days == 2, extend to 3 days to cover weekend
        if now.weekday() == 4 and days == 2:
            days = 3
            logger.info(f"Granted on Friday: automatically extending temporary pass for '{email_clean}' to 3 days (covers full weekend).")

        expires_at = now + timedelta(days=days)

        data = self._load_data()
        
        # Remove from permanent if moving to temp
        data["permanent_passes"].pop(email_clean, None)

        pass_info = {
            "granted_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "days": days,
            "customer_name": customer_name,
            "customer_id": customer_id
        }
        data["temporary_passes"][email_clean] = pass_info
        self._save_data(data)

        logger.info(f"Added temporary pass ({days} days) for '{email_clean}'. Expires at: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
        return pass_info

    def add_permanent_pass(self, email: str) -> Dict[str, Any]:
        """Adds a permanent pass for the given email."""
        email_clean = email.strip().lower()
        now = datetime.now()

        data = self._load_data()
        
        # Remove from temporary if upgrading to permanent
        data["temporary_passes"].pop(email_clean, None)

        pass_info = {
            "granted_at": now.isoformat()
        }
        data["permanent_passes"][email_clean] = pass_info
        self._save_data(data)

        logger.info(f"Added permanent pass for '{email_clean}'.")
        return pass_info

    def remove_pass(self, email: str):
        """Removes any temporary or permanent pass for the email."""
        email_clean = email.strip().lower()
        data = self._load_data()
        removed_temp = data["temporary_passes"].pop(email_clean, None)
        removed_perm = data["permanent_passes"].pop(email_clean, None)
        if removed_temp or removed_perm:
            self._save_data(data)

    def is_permanently_allowed(self, email: str) -> bool:
        """Returns True if user has a permanent pass."""
        email_clean = email.strip().lower()
        data = self._load_data()
        return email_clean in data.get("permanent_passes", {})

    def is_temporary_active(self, email: str, reference_time: Optional[datetime] = None) -> bool:
        """Returns True if user has a valid active temporary pass."""
        if reference_time is None:
            reference_time = datetime.now()

        email_clean = email.strip().lower()
        data = self._load_data()
        temp_info = data.get("temporary_passes", {}).get(email_clean)

        if not temp_info:
            return False

        expires_at = datetime.fromisoformat(temp_info["expires_at"])
        return reference_time < expires_at

    def get_expired_temporary_passes(self, reference_time: Optional[datetime] = None) -> List[Dict[str, str]]:
        """
        Returns a list of dicts with email, customer_name, and customer_id of expired temporary passes.
        Cleans up the expired passes from storage.
        """
        if reference_time is None:
            reference_time = datetime.now()

        data = self._load_data()
        expired_passes = []
        temp_passes = data.get("temporary_passes", {})
        remaining_passes = {}

        for email, pass_info in temp_passes.items():
            expires_at = datetime.fromisoformat(pass_info["expires_at"])
            if reference_time >= expires_at:
                expired_passes.append({
                    "email": email,
                    "customer_name": pass_info.get("customer_name", ""),
                    "customer_id": pass_info.get("customer_id", "")
                })
            else:
                remaining_passes[email] = pass_info

        if expired_passes:
            data["temporary_passes"] = remaining_passes
            self._save_data(data)

        return expired_passes
