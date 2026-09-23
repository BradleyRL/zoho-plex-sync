from datetime import datetime, date
from typing import Dict, List, Any, Optional
import requests
from config import config
from logger_service import logger

class ZohoBooksService:
    def __init__(self, cfg=config):
        self.cfg = cfg
        self._access_token: Optional[str] = None

    def refresh_access_token(self) -> str:
        """Refreshes the OAuth 2.0 access token using the refresh token."""
        url = f"{self.cfg.ZOHO_ACCOUNTS_URL}/oauth/v2/token"
        params = {
            "refresh_token": self.cfg.ZOHO_REFRESH_TOKEN,
            "client_id": self.cfg.ZOHO_CLIENT_ID,
            "client_secret": self.cfg.ZOHO_CLIENT_SECRET,
            "grant_type": "refresh_token"
        }
        
        logger.info("Refreshing Zoho Books access token...")
        response = requests.post(url, data=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if "access_token" not in data:
            error_msg = data.get("error", "Unknown error refreshing token")
            raise ValueError(f"Failed to refresh Zoho access token: {error_msg}")
        
        self._access_token = data["access_token"]
        return self._access_token

    def get_headers(self) -> Dict[str, str]:
        if not self._access_token:
            self.refresh_access_token()
        return {
            "Authorization": f"Zoho-oauthtoken {self._access_token}",
            "Content-Type": "application/json"
        }

    def fetch_contact_email(self, customer_id: str) -> Optional[str]:
        """Fetches contact email from Zoho Books if invoice does not contain it."""
        url = f"{self.cfg.ZOHO_BOOKS_API_URL}/contacts/{customer_id}"
        params = {"organization_id": self.cfg.ZOHO_ORGANIZATION_ID}
        try:
            resp = requests.get(url, headers=self.get_headers(), params=params, timeout=30)
            if resp.status_code == 200:
                contact = resp.json().get("contact", {})
                return contact.get("email") or contact.get("contact_persons", [{}])[0].get("email")
        except Exception as e:
            logger.warning(f"Could not fetch contact details for customer {customer_id}: {e}")
        return None

    def get_overdue_invoices(self) -> List[Dict[str, Any]]:
        """
        Fetches all overdue invoices from Zoho Books (handling pagination).
        """
        url = f"{self.cfg.ZOHO_BOOKS_API_URL}/invoices"
        page = 1
        all_invoices = []

        while True:
            params = {
                "organization_id": self.cfg.ZOHO_ORGANIZATION_ID,
                "status": "overdue",
                "page": page,
                "per_page": 200
            }
            logger.info(f"Fetching overdue invoices from Zoho Books (Page {page})...")
            resp = requests.get(url, headers=self.get_headers(), params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                raise RuntimeError(f"Zoho API returned error code {data.get('code')}: {data.get('message')}")

            invoices = data.get("invoices", [])
            all_invoices.extend(invoices)

            page_context = data.get("page_context", {})
            if not page_context.get("has_more_page", False):
                break
            page += 1

        return all_invoices

    @staticmethod
    def calculate_days_overdue(due_date_str: str, reference_date: Optional[date] = None) -> int:
        """
        Calculates how many days an invoice is overdue.
        Format expected: YYYY-MM-DD.
        """
        if reference_date is None:
            reference_date = datetime.now().date()
        
        due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
        days = (reference_date - due_date).days
        return days

    def get_users_to_disable(
        self,
        days_threshold: Optional[int] = None,
        reference_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Processes overdue invoices and aggregates users with invoices overdue by more than `days_threshold`.
        Returns a list of dicts:
        [
            {
                "email": "user@example.com",
                "customer_name": "John Doe",
                "customer_id": "12345",
                "invoice_numbers": ["INV-001"],
                "max_days_overdue": 5
            }
        ]
        """
        if days_threshold is None:
            days_threshold = self.cfg.OVERDUE_DAYS_THRESHOLD

        invoices = self.get_overdue_invoices()
        user_map: Dict[str, Dict[str, Any]] = {}

        for inv in invoices:
            due_date_str = inv.get("due_date")
            if not due_date_str:
                continue

            days_overdue = self.calculate_days_overdue(due_date_str, reference_date=reference_date)
            
            # Condition: strictly more than days_threshold (e.g. > 3 days)
            if days_overdue <= days_threshold:
                continue

            email = inv.get("email") or inv.get("customer_email")
            customer_id = inv.get("customer_id")

            # Fallback to fetch email from contact if not in invoice object
            if not email and customer_id:
                email = self.fetch_contact_email(customer_id)

            if not email:
                logger.warning(
                    f"Invoice {inv.get('invoice_number')} is {days_overdue} days overdue, "
                    f"but no email address found for customer '{inv.get('customer_name')}'."
                )
                continue

            email_clean = email.strip().lower()
            invoice_num = inv.get("invoice_number", "UNKNOWN")

            if email_clean not in user_map:
                user_map[email_clean] = {
                    "email": email_clean,
                    "customer_name": inv.get("customer_name", "Unknown"),
                    "customer_id": customer_id,
                    "invoice_numbers": [invoice_num],
                    "max_days_overdue": days_overdue
                }
            else:
                user_map[email_clean]["invoice_numbers"].append(invoice_num)
                user_map[email_clean]["max_days_overdue"] = max(
                    user_map[email_clean]["max_days_overdue"], days_overdue
                )

        return list(user_map.values())

    def get_email_by_recurring_invoice(self, invoice_number: str) -> Optional[Dict[str, Any]]:
        """
        Searches Zoho Books for a recurring invoice (or standard invoice) matching `invoice_number`
        and returns customer information including email.
        """
        clean_num = invoice_number.strip()
        logger.info(f"Searching Zoho Books for recurring invoice / invoice #: '{clean_num}'...")

        # 1. Search in Recurring Invoices endpoint
        rec_url = f"{self.cfg.ZOHO_BOOKS_API_URL}/recurringinvoices"
        params = {
            "organization_id": self.cfg.ZOHO_ORGANIZATION_ID,
            "search_text": clean_num
        }

        try:
            resp = requests.get(rec_url, headers=self.get_headers(), params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                rec_list = data.get("recurring_invoices", [])
                for rec in rec_list:
                    rec_num = rec.get("recurring_invoice_number", "")
                    if clean_num.lower() in rec_num.lower() or rec.get("recurring_invoice_id") == clean_num:
                        email = rec.get("email") or rec.get("customer_email")
                        customer_id = rec.get("customer_id")
                        if not email and customer_id:
                            email = self.fetch_contact_email(customer_id)
                        
                        if email:
                            return {
                                "email": email.strip().lower(),
                                "customer_name": rec.get("customer_name", "Unknown"),
                                "customer_id": customer_id,
                                "recurring_invoice_number": rec_num or clean_num,
                                "type": "recurring_invoice"
                            }
        except Exception as e:
            logger.warning(f"Failed to query recurring invoices endpoint: {e}")

        # 2. Fallback search in standard Invoices endpoint
        inv_url = f"{self.cfg.ZOHO_BOOKS_API_URL}/invoices"
        inv_params = {
            "organization_id": self.cfg.ZOHO_ORGANIZATION_ID,
            "invoice_number": clean_num
        }

        try:
            resp = requests.get(inv_url, headers=self.get_headers(), params=inv_params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                inv_list = data.get("invoices", [])
                for inv in inv_list:
                    if inv.get("invoice_number", "").lower() == clean_num.lower():
                        email = inv.get("email") or inv.get("customer_email")
                        customer_id = inv.get("customer_id")
                        if not email and customer_id:
                            email = self.fetch_contact_email(customer_id)
                        
                        if email:
                            return {
                                "email": email.strip().lower(),
                                "customer_name": inv.get("customer_name", "Unknown"),
                                "customer_id": customer_id,
                                "recurring_invoice_number": inv.get("invoice_number"),
                                "type": "invoice"
                            }
        except Exception as e:
            logger.warning(f"Failed to query standard invoices endpoint: {e}")

        return None

    def get_active_recurring_invoice_emails(self) -> set[str]:
        """
        Fetches all customer emails from Zoho Books that currently have an ACTIVE recurring invoice.
        Handles pagination.
        """
        url = f"{self.cfg.ZOHO_BOOKS_API_URL}/recurringinvoices"
        page = 1
        active_emails: set[str] = set()

        while True:
            params = {
                "organization_id": self.cfg.ZOHO_ORGANIZATION_ID,
                "status": "active",
                "page": page,
                "per_page": 200
            }
            logger.info(f"Fetching active recurring invoices from Zoho Books (Page {page})...")
            try:
                resp = requests.get(url, headers=self.get_headers(), params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                
                if data.get("code") != 0:
                    logger.error(f"Zoho API error: {data.get('message')}")
                    break

                rec_list = data.get("recurring_invoices", [])
                for rec in rec_list:
                    email = rec.get("email") or rec.get("customer_email")
                    customer_id = rec.get("customer_id")
                    if not email and customer_id:
                        email = self.fetch_contact_email(customer_id)
                    
                    if email:
                        active_emails.add(email.strip().lower())

                page_context = data.get("page_context", {})
                if not page_context.get("has_more_page", False):
                    break
                page += 1
            except Exception as e:
                logger.error(f"Failed to fetch active recurring invoices from Zoho Books: {e}")
                break

        return active_emails
