import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from logger_service import logger

class ZohoBooksService:
    def __init__(self, cfg):
        self.cfg = cfg
        self.access_token: Optional[str] = None

    def get_access_token(self) -> str:
        """
        Retrieves a valid OAuth2 access token using the refresh token.
        Always requests a fresh token to eliminate expiration edge cases.
        """
        url = f"{self.cfg.ZOHO_ACCOUNTS_URL}/oauth/v2/token"
        params = {
            "refresh_token": self.cfg.ZOHO_REFRESH_TOKEN,
            "client_id": self.cfg.ZOHO_CLIENT_ID,
            "client_secret": self.cfg.ZOHO_CLIENT_SECRET,
            "grant_type": "refresh_token"
        }
        
        logger.debug("Requesting new access token from Zoho OAuth endpoint...")
        resp = requests.post(url, params=params, timeout=30)
        
        if resp.status_code != 200:
            logger.error(f"Failed to refresh Zoho token: {resp.status_code} - {resp.text}")
            raise RuntimeError(f"Failed to refresh Zoho token: {resp.status_code} - {resp.text}")
            
        data = resp.json()
        if "access_token" not in data:
            logger.error(f"Access token missing in Zoho OAuth response: {data}")
            raise RuntimeError(f"Access token missing in response: {data}")

        self.access_token = data["access_token"]
        return self.access_token

    def get_headers(self) -> Dict[str, str]:
        token = self.get_access_token()
        return {
            "Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json"
        }

    def fetch_contact_email(self, customer_id: str) -> Optional[str]:
        """
        Fetches contact person details for a customer ID from Zoho Books
        to retrieve the primary email address if not included in invoice payload.
        """
        url = f"{self.cfg.ZOHO_BOOKS_API_URL}/contacts/{customer_id}"
        params = {"organization_id": self.cfg.ZOHO_ORGANIZATION_ID}
        try:
            resp = requests.get(url, headers=self.get_headers(), params=params, timeout=30)
            if resp.status_code == 200:
                contact = resp.json().get("contact", {})
                email = contact.get("email")
                if email:
                    return email.strip().lower()
                # Check contact persons array if top-level email is empty
                for cp in contact.get("contact_persons", []):
                    cp_email = cp.get("email")
                    if cp_email:
                        return cp_email.strip().lower()
        except Exception as e:
            logger.warning(f"Could not fetch contact details for customer {customer_id}: {e}")
        return None

    def get_overdue_invoices(self) -> List[Dict[str, Any]]:
        """
        Fetches all unpaid invoices from Zoho Books API across statuses: unpaid, overdue, sent, partially_paid.
        Handles pagination and deduping across status queries.
        """
        url = f"{self.cfg.ZOHO_BOOKS_API_URL}/invoices"
        invoice_map: Dict[str, Dict[str, Any]] = {}

        # Statuses to query to catch all unpaid or overdue invoices
        statuses = ["unpaid", "overdue", "sent", "partially_paid"]

        for status_filter in statuses:
            page = 1
            while True:
                params = {
                    "organization_id": self.cfg.ZOHO_ORGANIZATION_ID,
                    "status": status_filter,
                    "page": page,
                    "per_page": 200
                }
                logger.info(f"Fetching '{status_filter}' invoices from Zoho Books (Page {page})...")
                
                try:
                    resp = requests.get(url, headers=self.get_headers(), params=params, timeout=30)
                    resp.raise_for_status()
                    data = resp.json()
                    
                    if data.get("code") != 0:
                        logger.error(f"Zoho API error: {data.get('message')}")
                        break

                    invoices_page = data.get("invoices", [])
                    if not invoices_page:
                        break

                    for inv in invoices_page:
                        inv_id = inv.get("invoice_id")
                        if inv_id and inv_id not in invoice_map:
                            invoice_map[inv_id] = inv

                    page_context = data.get("page_context", {})
                    if not page_context.get("has_more_page", False):
                        break
                    page += 1
                except Exception as e:
                    logger.error(f"Error fetching '{status_filter}' invoices from Zoho Books: {e}")
                    break

        return list(invoice_map.values())

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
                "max_days_overdue": 5,
                "overdue_invoices_details": [...]
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

            customer_id = inv.get("customer_id")
            invoice_num = inv.get("invoice_number", "UNKNOWN")

            # Collect primary + all secondary contact person emails for this customer
            target_emails: set[str] = set()
            primary_email = inv.get("email") or inv.get("customer_email")
            if primary_email:
                target_emails.add(primary_email.strip().lower())

            if customer_id:
                contact_emails = self.fetch_all_contact_emails(customer_id)
                target_emails.update(contact_emails)

            if not target_emails:
                logger.warning(
                    f"Invoice {invoice_num} is {days_overdue} days overdue, "
                    f"but no email address found for customer '{inv.get('customer_name')}'."
                )
                continue

            invoice_id = inv.get("invoice_id")

            for email_clean in target_emails:
                inv_detail = {
                    "invoice_id": invoice_id,
                    "invoice_number": invoice_num,
                    "days_overdue": days_overdue,
                    "customer_id": customer_id
                }
                if email_clean not in user_map:
                    user_map[email_clean] = {
                        "email": email_clean,
                        "customer_name": inv.get("customer_name", "Unknown"),
                        "customer_id": customer_id,
                        "invoice_numbers": [invoice_num],
                        "max_days_overdue": days_overdue,
                        "overdue_invoices_details": [inv_detail]
                    }
                else:
                    if invoice_num not in user_map[email_clean]["invoice_numbers"]:
                        user_map[email_clean]["invoice_numbers"].append(invoice_num)
                        user_map[email_clean]["overdue_invoices_details"].append(inv_detail)
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

    def fetch_all_contact_emails(self, customer_id: str) -> list[str]:
        """
        Fetches primary and all secondary/additional contact person emails for a customer from Zoho Books.
        """
        url = f"{self.cfg.ZOHO_BOOKS_API_URL}/contacts/{customer_id}"
        params = {"organization_id": self.cfg.ZOHO_ORGANIZATION_ID}
        emails = []
        try:
            resp = requests.get(url, headers=self.get_headers(), params=params, timeout=30)
            if resp.status_code == 200:
                contact = resp.json().get("contact", {})
                primary = contact.get("email")
                if primary:
                    emails.append(primary.strip().lower())
                
                for cp in contact.get("contact_persons", []):
                    cp_email = cp.get("email")
                    if cp_email:
                        emails.append(cp_email.strip().lower())
        except Exception as e:
            logger.warning(f"Could not fetch contact person details for customer {customer_id}: {e}")
        return emails

    def get_active_recurring_invoice_emails(self) -> set[str]:
        """
        Fetches all customer emails (including primary and secondary contact persons)
        from Zoho Books that currently have an ACTIVE recurring invoice.
        Handles pagination and caches customer lookups.
        """
        url = f"{self.cfg.ZOHO_BOOKS_API_URL}/recurringinvoices"
        page = 1
        active_emails: set[str] = set()
        visited_customer_ids: set[str] = set()

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
                if not rec_list:
                    break

                for rec in rec_list:
                    email = rec.get("email") or rec.get("customer_email")
                    if email:
                        active_emails.add(email.strip().lower())

                    customer_id = rec.get("customer_id")
                    if customer_id and customer_id not in visited_customer_ids:
                        visited_customer_ids.add(customer_id)
                        # Fetch primary + all secondary contact person emails for this customer
                        contact_emails = self.fetch_all_contact_emails(customer_id)
                        active_emails.update(contact_emails)

                page_context = data.get("page_context", {})
                if not page_context.get("has_more_page", False):
                    break
                page += 1
            except Exception as e:
                logger.error(f"Failed to fetch active recurring invoices from Zoho Books: {e}")
                break

        return active_emails

    def _ensure_contact_person_email(self, contact_id: str, contact_name: str, email: str):
        """
        Ensures that the contact in Zoho Books (identified by contact_id)
        has a primary contact person with the specified email address.
        """
        clean_email = email.strip().lower()
        clean_name = contact_name.strip()
        name_parts = clean_name.split(maxsplit=1)
        first_name = name_parts[0] if name_parts else clean_name
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        url_contact = f"{self.cfg.ZOHO_BOOKS_API_URL}/contacts/{contact_id}"
        headers = self.get_headers()
        params = {"organization_id": self.cfg.ZOHO_ORGANIZATION_ID}

        try:
            resp = requests.get(url_contact, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                contact_data = resp.json().get("contact", {})
                contact_persons = contact_data.get("contact_persons", [])
                
                # Check if email is already present on primary or any contact person
                for cp in contact_persons:
                    if (cp.get("email") or "").strip().lower() == clean_email:
                        logger.info(f"Contact ID {contact_id} already has email '{clean_email}' attached.")
                        return

                if contact_persons:
                    # Update existing primary contact person with the email
                    primary_cp = next((cp for cp in contact_persons if cp.get("is_primary_contact")), contact_persons[0])
                    cp_id = primary_cp.get("contact_person_id")
                    url_cp_update = f"{self.cfg.ZOHO_BOOKS_API_URL}/contacts/contactpersons/{cp_id}"
                    cp_payload = {
                        "first_name": primary_cp.get("first_name") or first_name,
                        "last_name": primary_cp.get("last_name") or last_name,
                        "email": clean_email,
                        "is_primary_contact": True
                    }
                    logger.info(f"Updating contact person {cp_id} for customer {contact_id} with email '{clean_email}'...")
                    requests.put(url_cp_update, headers=headers, params=params, json=cp_payload, timeout=30)
                else:
                    # Create a new primary contact person
                    url_cp_create = f"{self.cfg.ZOHO_BOOKS_API_URL}/contacts/contactpersons"
                    cp_payload = {
                        "contact_id": contact_id,
                        "first_name": first_name,
                        "last_name": last_name,
                        "email": clean_email,
                        "is_primary_contact": True
                    }
                    logger.info(f"Creating new primary contact person for customer {contact_id} with email '{clean_email}'...")
                    requests.post(url_cp_create, headers=headers, params=params, json=cp_payload, timeout=30)

        except Exception as e:
            logger.warning(f"Could not verify/update contact person email for customer {contact_id}: {e}")

    def create_customer(self, contact_name: str, email: str, currency_code: str = "GTQ") -> str:
        """
        Creates a new customer contact in Zoho Books (or returns existing customer_id if email or name exists).
        Ensures the primary contact person has the specified email address.
        Default currency_code is 'GTQ'.
        """
        clean_email = email.strip().lower()
        clean_name = contact_name.strip()

        name_parts = clean_name.split(maxsplit=1)
        first_name = name_parts[0] if name_parts else clean_name
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        contact_persons = [
            {
                "first_name": first_name,
                "last_name": last_name,
                "email": clean_email,
                "is_primary_contact": True
            }
        ]

        url_contacts = f"{self.cfg.ZOHO_BOOKS_API_URL}/contacts"
        headers = self.get_headers()
        cid = None
        
        # 1. Search existing customer by email
        try:
            resp_email = requests.get(
                url_contacts,
                headers=headers,
                params={"organization_id": self.cfg.ZOHO_ORGANIZATION_ID, "email": clean_email},
                timeout=30
            )
            if resp_email.status_code == 200:
                contacts = resp_email.json().get("contacts", [])
                if contacts:
                    cid = str(contacts[0].get("contact_id"))
                    logger.info(f"Found existing customer in Zoho Books by email '{clean_email}': ID {cid}")
        except Exception as e:
            logger.warning(f"Error searching contact by email '{clean_email}': {e}")

        # 2. Search existing customer by contact_name / search_text if not found by email
        if not cid:
            try:
                resp_name = requests.get(
                    url_contacts,
                    headers=headers,
                    params={"organization_id": self.cfg.ZOHO_ORGANIZATION_ID, "search_text": clean_name},
                    timeout=30
                )
                if resp_name.status_code == 200:
                    contacts = resp_name.json().get("contacts", [])
                    for c in contacts:
                        if c.get("contact_name", "").strip().lower() == clean_name.lower():
                            cid = str(c.get("contact_id"))
                            logger.info(f"Found existing customer in Zoho Books by name '{clean_name}': ID {cid}")
                            break
            except Exception as e:
                logger.warning(f"Error searching contact by name '{clean_name}': {e}")

        # 3. Create new customer if not found
        if not cid:
            logger.info(f"Creating new customer in Zoho Books: '{clean_name}' ({clean_email})...")
            payload = {
                "contact_name": clean_name,
                "email": clean_email,
                "currency_code": currency_code,
                "contact_persons": contact_persons
            }
            
            resp = requests.post(
                url_contacts,
                headers=headers,
                params={"organization_id": self.cfg.ZOHO_ORGANIZATION_ID},
                json=payload,
                timeout=30
            )
            
            data = resp.json() if resp.content else {}

            # If currency_code causes error or bad request, retry without currency_code (uses org base currency)
            if resp.status_code not in (200, 201) or data.get("code") != 0:
                err_msg = data.get("message", f"HTTP {resp.status_code}")
                logger.warning(f"Initial create_customer attempt with currency_code='{currency_code}' returned: {err_msg}. Retrying without currency_code...")
                
                payload_fallback = {
                    "contact_name": clean_name,
                    "email": clean_email,
                    "contact_persons": contact_persons
                }
                resp_fallback = requests.post(
                    url_contacts,
                    headers=headers,
                    params={"organization_id": self.cfg.ZOHO_ORGANIZATION_ID},
                    json=payload_fallback,
                    timeout=30
                )
                data_fallback = resp_fallback.json() if resp_fallback.content else {}
                
                if resp_fallback.status_code in (200, 201) and data_fallback.get("code") == 0:
                    cid = str(data_fallback.get("contact", {}).get("contact_id"))
                    logger.info(f"Successfully created customer '{clean_name}' in Zoho Books (default currency). ID: {cid}")
                else:
                    final_msg = data_fallback.get("message") or data.get("message") or f"HTTP {resp.status_code}: {resp.text}"
                    code = data_fallback.get("code") or data.get("code")
                    logger.error(f"Zoho API error creating customer '{clean_name}': {final_msg} (Code {code})")
                    raise RuntimeError(f"Zoho API error creating customer: {final_msg} (Code {code})")
            else:
                cid = str(data.get("contact", {}).get("contact_id"))
                logger.info(f"Successfully created customer '{clean_name}' in Zoho Books. ID: {cid}")

        # 4. Guarantee the primary contact person has the email address set
        if cid:
            self._ensure_contact_person_email(cid, clean_name, clean_email)

        return cid

    def create_recurring_invoice(
        self,
        customer_id: str,
        recurrence_name: str,
        start_date: str,
        item_id: str = "5251269000000090022",
        quantity: int = 1,
        never_expires: bool = True,
        payment_terms: int = 0
    ) -> Dict[str, Any]:
        """
        Creates a new Recurring Invoice in Zoho Books upon temporary pass expiration.
        """
        url = f"{self.cfg.ZOHO_BOOKS_API_URL}/recurringinvoices"
        params = {"organization_id": self.cfg.ZOHO_ORGANIZATION_ID}
        
        payload = {
            "customer_id": customer_id,
            "recurrence_name": recurrence_name,
            "recurrence_frequency": "months",
            "repeat_every": 1,
            "start_date": start_date,
            "never_expires": never_expires,
            "payment_terms": payment_terms,
            "line_items": [
                {
                    "item_id": item_id,
                    "quantity": quantity
                }
            ]
        }

        logger.info(f"Creating Recurring Invoice in Zoho Books for customer ID '{customer_id}' ({recurrence_name})...")
        resp = requests.post(url, headers=self.get_headers(), params=params, json=payload, timeout=30)
        data = resp.json() if resp.content else {}

        if resp.status_code not in (200, 201) or data.get("code") != 0:
            err_msg = data.get("message") or f"HTTP {resp.status_code}: {resp.text}"
            code = data.get("code")
            logger.error(f"Zoho API error creating recurring invoice: {err_msg} (Code {code})")
            raise RuntimeError(f"Zoho API error creating recurring invoice: {err_msg} (Code {code})")

        rec_invoice = data.get("recurring_invoice", {})
        rec_id = rec_invoice.get("recurring_invoice_id")
        rec_num = rec_invoice.get("recurring_invoice_number", rec_id)
        logger.info(f"Successfully created Recurring Invoice #{rec_num} for customer '{recurrence_name}'.")
        return rec_invoice

    def void_invoice(self, invoice_id: str, reason: str = "No Renovó") -> Dict[str, Any]:
        """
        Marks an invoice as VOID in Zoho Books with the specified reason.
        API Endpoint: POST /invoices/{invoice_id}/status/void
        """
        if not invoice_id:
            logger.warning("void_invoice called without invoice_id. Skipping.")
            return {}

        url = f"{self.cfg.ZOHO_BOOKS_API_URL}/invoices/{invoice_id}/status/void"
        params = {
            "organization_id": self.cfg.ZOHO_ORGANIZATION_ID,
            "reason": reason
        }
        logger.info(f"Marking invoice ID '{invoice_id}' as VOID in Zoho Books (Reason: '{reason}')...")
        resp = requests.post(url, headers=self.get_headers(), params=params, json={"reason": reason}, timeout=30)
        data = resp.json() if resp.content else {}

        if resp.status_code not in (200, 201) or data.get("code") != 0:
            err_msg = data.get("message") or f"HTTP {resp.status_code}: {resp.text}"
            logger.error(f"Zoho API error voiding invoice '{invoice_id}': {err_msg}")
            raise RuntimeError(f"Zoho API error voiding invoice: {err_msg}")

        logger.info(f"Successfully voided invoice '{invoice_id}' in Zoho Books.")
        return data

    def stop_recurring_invoices_for_customer(self, customer_id: str) -> List[Dict[str, Any]]:
        """
        Fetches all active recurring invoices for a customer and stops them.
        API Endpoint: POST /recurringinvoices/{recurring_invoice_id}/status/stop
        """
        if not customer_id:
            logger.warning("stop_recurring_invoices_for_customer called without customer_id. Skipping.")
            return []

        url_search = f"{self.cfg.ZOHO_BOOKS_API_URL}/recurringinvoices"
        params_search = {
            "organization_id": self.cfg.ZOHO_ORGANIZATION_ID,
            "customer_id": customer_id,
            "status": "active"
        }
        stopped = []
        try:
            resp = requests.get(url_search, headers=self.get_headers(), params=params_search, timeout=30)
            if resp.status_code == 200:
                rec_list = resp.json().get("recurring_invoices", [])
                for rec in rec_list:
                    rec_id = rec.get("recurring_invoice_id")
                    rec_num = rec.get("recurring_invoice_number", rec_id)
                    if rec_id:
                        url_stop = f"{self.cfg.ZOHO_BOOKS_API_URL}/recurringinvoices/{rec_id}/status/stop"
                        params_stop = {"organization_id": self.cfg.ZOHO_ORGANIZATION_ID}
                        logger.info(f"Stopping active recurring invoice #{rec_num} (ID: {rec_id}) for customer {customer_id}...")
                        resp_stop = requests.post(url_stop, headers=self.get_headers(), params=params_stop, timeout=30)
                        data_stop = resp_stop.json() if resp_stop.content else {}
                        if resp_stop.status_code in (200, 201) and data_stop.get("code") == 0:
                            logger.info(f"Stopped recurring invoice #{rec_num} for customer {customer_id}.")
                            stopped.append({"recurring_invoice_id": rec_id, "recurring_invoice_number": rec_num})
                        else:
                            logger.warning(f"Could not stop recurring invoice #{rec_num}: {data_stop.get('message')}")
        except Exception as e:
            logger.error(f"Error stopping recurring invoices for customer {customer_id}: {e}")

        return stopped
