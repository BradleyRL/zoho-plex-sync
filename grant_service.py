from __future__ import annotations
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
        """Creates data directory and grants.json if they do not exist."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            initial_data = {"temporary_passes": [], "permanent_passes": []}
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(initial_data, f, indent=2)

    def _load_data(self) -> Dict[str, Any]:
        """Loads data from grants.json safely, normalizing temporary_passes & permanent_passes into lists."""
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}

                temp_passes = data.get("temporary_passes")
                if isinstance(temp_passes, list):
                    pass
                elif isinstance(temp_passes, dict):
                    # Convert dict keys or values to list format
                    converted_temp = []
                    for k, v in temp_passes.items():
                        if isinstance(v, dict):
                            converted_temp.append(v)
                        else:
                            converted_temp.append({"email": str(k).strip().lower()})
                    data["temporary_passes"] = converted_temp
                else:
                    data["temporary_passes"] = []

                perm_passes = data.get("permanent_passes")
                if isinstance(perm_passes, list):
                    pass
                elif isinstance(perm_passes, dict):
                    data["permanent_passes"] = [str(k).strip().lower() for k in perm_passes.keys()]
                else:
                    data["permanent_passes"] = []

                return data
        except Exception as e:
            logger.error(f"Error reading grants file '{self.file_path}': {e}")
            return {"temporary_passes": [], "permanent_passes": []}

    def _save_data(self, data: Dict[str, Any]):
        """Saves data back to grants.json safely."""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving grants file '{self.file_path}': {e}")

    @staticmethod
    def _get_pass_email(p: Any) -> str:
        if isinstance(p, dict):
            return str(p.get("email", "")).strip().lower()
        elif isinstance(p, str):
            return p.strip().lower()
        return ""

    @staticmethod
    def _get_pass_expires_at(p: Any) -> str:
        if isinstance(p, dict):
            return str(p.get("expires_at", ""))
        return ""

    def add_temporary_pass(
        self,
        email: str,
        customer_name: Optional[str] = None,
        customer_id: Optional[str] = None,
        days: int = 2,
        reference_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Opción 1: Grants a temporary 2-day pass to an email address.
        If granted on Friday (weekday 4), extends pass to 3 days to cover the full weekend.
        """
        clean_email = email.strip().lower()
        now = reference_time or datetime.now()

        # Business logic rule: If today is Friday (weekday 4), grant 3 days instead of 2
        effective_days = days
        if days == 2 and now.weekday() == 4:
            effective_days = 3
            logger.info(f"Today is Friday! Automatically extending temporary pass for '{clean_email}' to {effective_days} days.")

        expires_at = (now + timedelta(days=effective_days)).strftime("%Y-%m-%d %H:%M:%S")
        created_at = now.strftime("%Y-%m-%d %H:%M:%S")

        data = self._load_data()
        
        # Remove any existing temporary pass for this email
        data["temporary_passes"] = [
            p for p in data.get("temporary_passes", []) 
            if self._get_pass_email(p) != clean_email
        ]

        new_pass = {
            "email": clean_email,
            "customer_name": customer_name or clean_email,
            "customer_id": customer_id or "",
            "created_at": created_at,
            "expires_at": expires_at,
            "days": effective_days,
            "days_granted": effective_days
        }

        data["temporary_passes"].append(new_pass)
        self._save_data(data)
        
        logger.info(f"Granted temporary pass to '{clean_email}' ({effective_days} days, expires: {expires_at}).")
        return new_pass

    def add_permanent_pass(self, email: str) -> Dict[str, Any]:
        """
        Opción 3: Grants a permanent pass to an email address.
        """
        clean_email = email.strip().lower()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        data = self._load_data()
        
        # Remove any existing temp pass for this email
        data["temporary_passes"] = [
            p for p in data.get("temporary_passes", []) 
            if self._get_pass_email(p) != clean_email
        ]

        existing_perm = [self._get_pass_email(p) for p in data.get("permanent_passes", [])]
        if clean_email not in existing_perm:
            data["permanent_passes"].append(clean_email)
            self._save_data(data)
            logger.info(f"Added permanent pass for '{clean_email}'.")

        return {"email": clean_email, "created_at": created_at}

    def remove_pass(self, email: str):
        """Removes any temporary or permanent pass for an email."""
        clean_email = email.strip().lower()
        data = self._load_data()
        
        data["temporary_passes"] = [
            p for p in data.get("temporary_passes", []) 
            if self._get_pass_email(p) != clean_email
        ]
        data["permanent_passes"] = [
            p for p in data.get("permanent_passes", []) 
            if self._get_pass_email(p) != clean_email
        ]
        self._save_data(data)

    def is_temporary_active(self, email: str, reference_time: Optional[datetime] = None) -> bool:
        """Checks if a user currently has an ACTIVE (unexpired) temporary pass."""
        clean_email = email.strip().lower()
        data = self._load_data()
        now = reference_time or datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")

        for pass_info in data.get("temporary_passes", []):
            if self._get_pass_email(pass_info) == clean_email:
                expires_at = self._get_pass_expires_at(pass_info)
                if expires_at and expires_at > now_str:
                    return True
        return False

    def is_permanently_allowed(self, email: str) -> bool:
        """Checks if an email is registered on the permanent passes whitelist."""
        clean_email = email.strip().lower()
        data = self._load_data()
        existing_perm = [self._get_pass_email(p) for p in data.get("permanent_passes", [])]
        return clean_email in existing_perm

    def get_expired_temporary_passes(self, reference_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Returns all temporary passes that have passed their `expires_at` timestamp and cleans them up."""
        data = self._load_data()
        now = reference_time or datetime.now()
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        expired = []
        remaining = []

        for pass_info in data.get("temporary_passes", []):
            email = self._get_pass_email(pass_info)
            expires_at = self._get_pass_expires_at(pass_info)
            if not expires_at or expires_at <= now_str:
                if email:
                    expired.append({
                        "email": email,
                        "customer_name": pass_info.get("customer_name") if isinstance(pass_info, dict) else email,
                        "customer_id": pass_info.get("customer_id") if isinstance(pass_info, dict) else ""
                    })
            else:
                remaining.append(pass_info)

        if expired:
            data["temporary_passes"] = remaining
            self._save_data(data)

        return expired
