#!/usr/bin/env python3
"""
Zoho Books Overdue Invoices to Plex Access Sync & Access Management Script.

This script manages Plex library access based on Zoho Books overdue invoices (> 3 days),
and supports CLI options for:
 1. Granting 2-day temporary access by email (--grant-temp email --name customer_name)
 2. Granting access by Zoho Recurring Invoice # (--grant-invoice #)
 3. Granting permanent access by email (--grant-permanent email)
"""

import sys
import argparse
from datetime import datetime
from config import config
from logger_service import logger, log_disabled_user
from zoho_service import ZohoBooksService
from plex_service import PlexService
from grant_service import GrantService

def parse_args():
    parser = argparse.ArgumentParser(
        description="Sync Zoho Books overdue invoices with Plex library access & manage user grants."
    )
    
    # Modes / Actions
    parser.add_argument(
        "--grant-temp",
        type=str,
        metavar="EMAIL",
        help="Opción 1: Grant temporary access to EMAIL (valid for N days, default 2 days)."
    )
    parser.add_argument(
        "--name",
        type=str,
        metavar="CUSTOMER_NAME",
        help="Customer name required when granting temporary access (--grant-temp)."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=2,
        help="Number of days for temporary pass (default: 2 days)."
    )
    parser.add_argument(
        "--grant-invoice",
        type=str,
        metavar="RECURRING_INVOICE_NUM",
        help="Opción 2: Grant access to user by Zoho Recurring Invoice #."
    )
    parser.add_argument(
        "--grant-permanent",
        type=str,
        metavar="EMAIL",
        help="Opción 3: Grant permanent access to EMAIL."
    )
    parser.add_argument(
        "--list-inactive-plex",
        action="store_true",
        help="Opción 4: List Plex users who do NOT have an ACTIVE recurring invoice in Zoho Books."
    )
    parser.add_argument(
        "--show-invoices",
        action="store_true",
        help="Debug: Fetch and display all unpaid/overdue invoices from Zoho Books."
    )

    # General options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without modifying Plex library access."
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help=f"Override overdue days threshold (default from env: {config.OVERDUE_DAYS_THRESHOLD})"
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate configuration settings and exit."
    )
    return parser.parse_args()

def handle_grant_temp(
    email: str,
    customer_name: str,
    days: int,
    zoho_service: ZohoBooksService,
    plex_service: PlexService,
    grant_service: GrantService,
    dry_run: bool
):
    """Opción 1: Grant temporary access valid for N days, creating customer in Zoho Books."""
    if not customer_name:
        logger.error("Error: --name [CUSTOMER_NAME] is required when using --grant-temp.")
        sys.exit(1)

    logger.info(f"[OPTION 1] Creating/fetching customer '{customer_name}' in Zoho Books (currency GTQ)...")
    if dry_run:
        logger.info(f"[DRY-RUN] Would create customer '{customer_name}' ({email}) in Zoho Books with currency GTQ.")
        customer_id = "DRY_RUN_CUSTOMER_ID"
    else:
        try:
            customer_id = zoho_service.create_customer(contact_name=customer_name, email=email, currency_code="GTQ")
        except Exception as e:
            logger.error(f"Failed to create customer in Zoho Books: {e}")
            sys.exit(1)

    logger.info(f"[OPTION 1] Granting temporary access for '{email}' ({days} days)...")
    pass_info = grant_service.add_temporary_pass(
        email=email,
        customer_name=customer_name,
        customer_id=customer_id,
        days=days
    )
    result = plex_service.grant_user_access(email=email, dry_run=dry_run)
    
    log_disabled_user(
        email=email,
        customer_name=customer_name,
        invoice_numbers=["TEMP-PASS"],
        max_days_overdue=0,
        action=f"Granted temporary access ({days} days, expires {pass_info['expires_at']})",
        status=result["status"],
        dry_run=dry_run
    )
    logger.info(f"Temporary pass granted successfully for '{email}' (Zoho Customer ID: {customer_id}). Result: {result['status']}")

def handle_grant_invoice(invoice_num: str, zoho_service: ZohoBooksService, plex_service: PlexService, grant_service: GrantService, dry_run: bool):
    """Opción 2: Grant access by entering Zoho Recurring Invoice #."""
    logger.info(f"[OPTION 2] Searching Zoho Books for recurring invoice #: '{invoice_num}'...")
    info = zoho_service.get_email_by_recurring_invoice(invoice_num)
    if not info or not info.get("email"):
        logger.error(f"Could not find customer email for recurring invoice / invoice #: '{invoice_num}'.")
        sys.exit(1)

    email = info["email"]
    customer_name = info.get("customer_name", "Customer")
    rec_num = info.get("recurring_invoice_number", invoice_num)
    logger.info(f"Found customer '{customer_name}' ({email}) for recurring invoice '{rec_num}'.")

    # Clear temporary pass if existing, and grant access
    grant_service.remove_pass(email)
    result = plex_service.grant_user_access(email=email, dry_run=dry_run)

    log_disabled_user(
        email=email,
        customer_name=customer_name,
        invoice_numbers=[f"REC-INV:{rec_num}"],
        max_days_overdue=0,
        action=f"Granted access via recurring invoice #{rec_num}",
        status=result["status"],
        dry_run=dry_run
    )
    logger.info(f"Access granted successfully for '{email}' via recurring invoice #{rec_num}.")

def handle_grant_permanent(email: str, plex_service: PlexService, grant_service: GrantService, dry_run: bool):
    """Opción 3: Grant permanent access by email."""
    logger.info(f"[OPTION 3] Granting permanent access for '{email}'...")
    grant_service.add_permanent_pass(email=email)
    result = plex_service.grant_user_access(email=email, dry_run=dry_run)

    log_disabled_user(
        email=email,
        customer_name="Permanent Pass",
        invoice_numbers=["PERMANENT-PASS"],
        max_days_overdue=0,
        action="Granted permanent library access",
        status=result["status"],
        dry_run=dry_run
    )
    logger.info(f"Permanent pass granted successfully for '{email}'. Result: {result['status']}")

def handle_list_inactive_plex(zoho_service: ZohoBooksService, plex_service: PlexService, grant_service: GrantService):
    """Opción 4: List Plex users who do NOT have an ACTIVE recurring invoice in Zoho Books."""
    logger.info("[OPTION 4] Fetching all shared users from Plex...")
    try:
        plex_users = plex_service.get_all_shared_users()
    except Exception as e:
        logger.error(f"Failed to fetch Plex shared users: {e}")
        sys.exit(1)

    if not plex_users:
        logger.info("No shared users found on Plex.")
        sys.exit(0)

    logger.info("Fetching active recurring invoices from Zoho Books...")
    active_emails = zoho_service.get_active_recurring_invoice_emails()
    logger.info(f"Found {len(active_emails)} active recurring invoice email(s) in Zoho Books.")

    inactive_plex_users = []

    for u in plex_users:
        email = u["email"]
        username = u["username"]
        title = u["title"]

        # Check if email/username is in Zoho active recurring invoices
        is_active_in_zoho = (
            (email and email in active_emails) or
            (username and username.lower() in active_emails) or
            (title and title.lower() in active_emails)
        )

        has_perm_pass = grant_service.is_permanently_allowed(email) if email else False
        has_temp_pass = grant_service.is_temporary_active(email) if email else False

        if not is_active_in_zoho:
            reason = "No active recurring invoice in Zoho Books"
            if has_perm_pass:
                reason += " (Has PERMANENT pass)"
            elif has_temp_pass:
                reason += " (Has ACTIVE temporary pass)"

            inactive_plex_users.append({
                "email": email or "(No Email)",
                "username": username or title or "Unknown",
                "reason": reason
            })

    logger.info("==================================================")
    logger.info(f"Plex Users WITHOUT Active Recurring Invoice ({len(inactive_plex_users)} total):")
    logger.info("==================================================")

    if not inactive_plex_users:
        logger.info("All Plex users currently have an active recurring invoice in Zoho Books!")
        sys.exit(0)

    print(f"\n{'EMAIL':<35} | {'USERNAME':<20} | {'NOTE'}")
    print("-" * 80)
    for user in inactive_plex_users:
        print(f"{user['email']:<35} | {user['username']:<20} | {user['reason']}")
    print("-" * 80 + "\n")

def handle_show_invoices(zoho_service: ZohoBooksService, threshold: int):
    """Debug: Displays all unpaid/overdue invoices retrieved from Zoho Books."""
    logger.info("[DEBUG] Fetching all unpaid & overdue invoices from Zoho Books...")
    try:
        invoices = zoho_service.get_overdue_invoices()
    except Exception as e:
        logger.error(f"Failed to fetch invoices: {e}")
        sys.exit(1)

    if not invoices:
        logger.info("No unpaid/overdue invoices found in Zoho Books.")
        sys.exit(0)

    print(f"\nFound {len(invoices)} total unpaid/overdue invoice(s) in Zoho Books:\n")
    print(f"{'INVOICE #':<15} | {'CUSTOMER':<20} | {'EMAIL':<30} | {'DUE DATE':<10} | {'DAYS OVERDUE':<12} | {'> 3 DAYS?'}")
    print("-" * 110)

    for inv in invoices:
        num = inv.get("invoice_number", "UNKNOWN")
        name = inv.get("customer_name", "Unknown")[:20]
        email = inv.get("email") or inv.get("customer_email") or "(No Email)"
        email = email[:30]
        due_date = inv.get("due_date", "N/A")
        
        days_overdue = 0
        if due_date != "N/A":
            try:
                days_overdue = zoho_service.calculate_days_overdue(due_date)
            except Exception:
                pass

        is_overdue_threshold = "YES (MATCH)" if days_overdue > threshold else f"NO (<= {threshold}d)"
        print(f"{num:<15} | {name:<20} | {email:<30} | {due_date:<10} | {days_overdue:<12} | {is_overdue_threshold}")

    print("-" * 110 + "\n")

def main():
    args = parse_args()

    if args.check_config:
        missing = config.validate()
        if missing:
            logger.error(f"Missing required configuration variables in .env: {', '.join(missing)}")
            sys.exit(1)
        logger.info("Configuration is valid.")
        sys.exit(0)

    # Validate configuration before running
    missing = config.validate()
    if missing:
        logger.error(
            f"Configuration error: missing environment variables: {', '.join(missing)}. "
            f"Please check your .env file."
        )
        sys.exit(1)

    zoho_service = ZohoBooksService(cfg=config)
    plex_service = PlexService(cfg=config)
    grant_service = GrantService()

    # Handle direct CLI grant commands if specified
    if args.grant_temp:
        handle_grant_temp(
            email=args.grant_temp,
            customer_name=args.name,
            days=args.days,
            zoho_service=zoho_service,
            plex_service=plex_service,
            grant_service=grant_service,
            dry_run=args.dry_run
        )
        sys.exit(0)

    if args.grant_invoice:
        handle_grant_invoice(
            invoice_num=args.grant_invoice,
            zoho_service=zoho_service,
            plex_service=plex_service,
            grant_service=grant_service,
            dry_run=args.dry_run
        )
        sys.exit(0)

    if args.grant_permanent:
        handle_grant_permanent(
            email=args.grant_permanent,
            plex_service=plex_service,
            grant_service=grant_service,
            dry_run=args.dry_run
        )
        sys.exit(0)

    if args.list_inactive_plex:
        handle_list_inactive_plex(
            zoho_service=zoho_service,
            plex_service=plex_service,
            grant_service=grant_service
        )
        sys.exit(0)

    if args.show_invoices:
        threshold = args.threshold if args.threshold is not None else config.OVERDUE_DAYS_THRESHOLD
        handle_show_invoices(zoho_service=zoho_service, threshold=threshold)
        sys.exit(0)

    # Standard Daily Sync Execution
    threshold = args.threshold if args.threshold is not None else config.OVERDUE_DAYS_THRESHOLD
    logger.info("==================================================")
    logger.info("Starting Daily Zoho Books -> Plex Overdue Sync Process")
    logger.info(f"Overdue Threshold: > {threshold} days")
    logger.info(f"Execution Mode: {'[DRY-RUN]' if args.dry_run else '[LIVE]'}")
    logger.info("==================================================")

    # STEP 1: Process and revoke expired 2-day temporary passes & create Recurring Invoices in Zoho
    expired_temp_passes = grant_service.get_expired_temporary_passes()
    if expired_temp_passes:
        logger.info(f"Found {len(expired_temp_passes)} expired temporary pass(es). Processing...")
        today_str = datetime.now().strftime("%Y-%m-%d")
        for pass_info in expired_temp_passes:
            expired_email = pass_info["email"]
            customer_name = pass_info.get("customer_name") or expired_email
            customer_id = pass_info.get("customer_id")

            # Create recurring invoice in Zoho Books if customer_id exists
            if customer_id:
                if args.dry_run:
                    logger.info(f"[DRY-RUN] Would create Recurring Invoice in Zoho Books for '{customer_name}' (ID: {customer_id}).")
                else:
                    try:
                        zoho_service.create_recurring_invoice(
                            customer_id=customer_id,
                            recurrence_name=customer_name,
                            start_date=today_str,
                            item_id="5251269000000090022",
                            quantity=1,
                            never_expires=True,
                            payment_terms=0
                        )
                        logger.info(f"Created Recurring Invoice in Zoho Books for '{customer_name}'.")
                    except Exception as e:
                        logger.error(f"Failed to create Recurring Invoice for '{customer_name}': {e}")
            else:
                logger.warning(f"No customer_id saved for expired pass '{expired_email}'. Skipping Recurring Invoice creation.")

            # Revoke access on Plex directly
            revoke_res = plex_service.revoke_user_access(email=expired_email, dry_run=args.dry_run)
            log_disabled_user(
                email=expired_email,
                customer_name=f"{customer_name} (Expired Pass)",
                invoice_numbers=["EXPIRED-PASS"],
                max_days_overdue=0,
                action="Access revoked & recurring invoice created: temporary pass expired",
                status=revoke_res["status"],
                dry_run=args.dry_run
            )
            logger.info(f"Revoked access for expired temporary pass '{expired_email}'. Status: {revoke_res['status']}")

    # STEP 2: Process Zoho Books Overdue Invoices
    try:
        users_to_disable = zoho_service.get_users_to_disable(days_threshold=threshold)
    except Exception as e:
        logger.error(f"Failed to fetch overdue users from Zoho Books: {e}")
        sys.exit(1)

    # Filter out users with an active temporary pass (active grace period)
    filtered_users_to_disable = []
    for user_info in users_to_disable:
        email = user_info["email"]
        if grant_service.is_temporary_active(email):
            logger.info(f"Skipping overdue enforcement for '{email}': User has an ACTIVE temporary pass.")
            continue
        filtered_users_to_disable.append(user_info)

    if not filtered_users_to_disable:
        logger.info("No overdue users requiring access revocation today. Sync complete.")
        sys.exit(0)

    logger.info(f"Found {len(filtered_users_to_disable)} user(s) with overdue invoices > {threshold} days to process.")

    success_count = 0
    already_disabled_count = 0
    not_found_count = 0
    failed_count = 0

    for user_info in filtered_users_to_disable:
        email = user_info["email"]
        customer_name = user_info["customer_name"]
        invoice_numbers = user_info["invoice_numbers"]
        max_days = user_info["max_days_overdue"]

        result = plex_service.revoke_user_access(email=email, dry_run=args.dry_run)

        log_disabled_user(
            email=email,
            customer_name=customer_name,
            invoice_numbers=invoice_numbers,
            max_days_overdue=max_days,
            action=result["action"],
            status=result["status"],
            dry_run=args.dry_run
        )

        if result["status"] in ("SUCCESS", "DRY_RUN"):
            success_count += 1
        elif result["status"] == "ALREADY_DISABLED":
            already_disabled_count += 1
        elif result["status"] == "NOT_FOUND":
            not_found_count += 1
        else:
            failed_count += 1

    logger.info("--------------------------------------------------")
    logger.info(
        f"Processing finished. Total: {len(filtered_users_to_disable)} | "
        f"Revoked/Updated: {success_count} | Already Disabled: {already_disabled_count} | "
        f"Plex Not Found: {not_found_count} | Failed: {failed_count}"
    )
    logger.info("==================================================")

if __name__ == "__main__":
    main()
