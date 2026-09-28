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
                            v_copy = dict(v)
                            if "email" not in v_copy:
                                v_copy["email"] = str(k).strip().lower()
                            converted_temp.append(v_copy)
                        else:
                            converted_temp.append({
                                "email": str(k).strip().lower(),
                                "expires_at": str(v)
                            })
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
            email = p.get("email") or p.get("user") or p.get("mail")
            if email:
                return str(email).strip().lower()
            for k in p.keys():
                if "@" in str(k):
                    return str(k).strip().lower()
            return ""
        elif isinstance(p, str):
            return p.strip().lower()
        return ""

    @staticmethod
    def _get_pass_expires_at(p: Any) -> str:
        if isinstance(p, dict):
            for key in ("expires_at", "expiration", "expires", "valid_until", "expire"):
                if key in p and p[key]:
                    return str(p[key])
            for v in p.values():
                if isinstance(v, str) and ("202" in v or "-" in v):
                    return str(v)
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

    @staticmethod
    def _parse_datetime(val: Any) -> Optional[datetime]:
        if not val:
            return None
        if isinstance(val, datetime):
            dt = val
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        val_str = str(val).strip()
        if not val_str:
            return None
        clean_str = val_str.replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(clean_str, fmt)
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
                return dt
            except ValueError:
                pass
        try:
            dt = datetime.fromisoformat(val_str)
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except ValueError:
            pass
        return None

    def is_temporary_active(self, email: str, reference_time: Optional[datetime] = None) -> bool:
        """Checks if a user currently has an ACTIVE (unexpired) temporary pass."""
        clean_email = email.strip().lower()
        data = self._load_data()
        now = reference_time or datetime.now()

        for pass_info in data.get("temporary_passes", []):
            if self._get_pass_email(pass_info) == clean_email:
                expires_at_raw = self._get_pass_expires_at(pass_info)
                dt_expires = self._parse_datetime(expires_at_raw)
                if dt_expires and dt_expires > now:
                    return True
        return False

    def is_permanently_allowed(self, email: str) -> bool:
        """Checks if an email is registered on the permanent passes whitelist."""
        clean_email = email.strip().lower()
        data = self._load_data()
        existing_perm = [self._get_pass_email(p) for p in data.get("permanent_passes", [])]
        return clean_email in existing_perm

    def get_expired_temporary_passes(
        self,
        reference_time: Optional[datetime] = None,
        zoho_service: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """Returns all temporary passes that have passed their `expires_at` timestamp and cleans them up."""
        data = self._load_data()
        now = reference_time or datetime.now()
        expired = []
        remaining = []

        all_passes = data.get("temporary_passes", [])
        logger.info(f"GrantService: Inspecting {len(all_passes)} temporary pass(es) in grants.json against current time {now.strftime('%Y-%m-%d %H:%M:%S')}...")

        for pass_info in all_passes:
            email = self._get_pass_email(pass_info)
            customer_id = pass_info.get("customer_id") if isinstance(pass_info, dict) else ""
            cust_name = pass_info.get("customer_name") if isinstance(pass_info, dict) else ""

            # If email is missing in pass_info but customer_id is present, resolve email from Zoho Books
            if not email and customer_id and zoho_service:
                try:
                    if hasattr(zoho_service, "fetch_contact_email"):
                        fetched_email = zoho_service.fetch_contact_email(customer_id)
                        if fetched_email:
                            email = fetched_email.strip().lower()
                            logger.info(f"GrantService: Resolved missing email for customer_id '{customer_id}' -> '{email}' via Zoho Books.")
                except Exception as e:
                    logger.warning(f"GrantService: Could not resolve email for customer_id '{customer_id}': {e}")

            expires_at_raw = self._get_pass_expires_at(pass_info)
            dt_expires = self._parse_datetime(expires_at_raw)

            logger.info(f"GrantService check: email='{email}', customer_id='{customer_id}', expires_at_raw='{expires_at_raw}', parsed={dt_expires}")

            if not dt_expires or dt_expires <= now:
                if email:
                    logger.info(f"GrantService: Temporary pass for '{email}' (Customer: {cust_name}) is EXPIRED (expires: {expires_at_raw}).")
                    expired.append({
                        "email": email,
                        "customer_name": cust_name or email,
                        "customer_id": customer_id or ""
                    })
                elif customer_id:
                    logger.warning(f"GrantService: Temporary pass with customer_id '{customer_id}' (name: {cust_name}) is expired but email could not be resolved.")
            else:
                logger.info(f"GrantService: Temporary pass for '{email or customer_id}' is still ACTIVE until {expires_at_raw}.")
                remaining.append(pass_info)

        if expired:
            data["temporary_passes"] = remaining
            self._save_data(data)

        return expired
