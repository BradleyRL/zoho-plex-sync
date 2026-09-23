import logging
import sys
from datetime import datetime
from pathlib import Path
from config import config

def setup_logger(name: str = "overdue_plex_sync") -> logging.Logger:
    """Configures console logging and daily file logging on disk."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    # Ensure log directory exists
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Daily log file path: e.g. logs/disabled_users_2026-09-23.log
    today_str = datetime.now().strftime("%Y-%m-%d")
    log_file_path = config.LOG_DIR / f"disabled_users_{today_str}.log"

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

logger = setup_logger()

def log_disabled_user(
    email: str,
    customer_name: str,
    invoice_numbers: list[str],
    max_days_overdue: int,
    action: str,
    status: str,
    dry_run: bool = False
):
    """
    Logs a detailed record of a disabled user to disk and console.
    """
    prefix = "[DRY-RUN] " if dry_run else ""
    invoices_str = ", ".join(invoice_numbers)
    msg = (
        f"{prefix}Status: {status} | Email: {email} | Customer: '{customer_name}' | "
        f"Invoices: [{invoices_str}] | Max Overdue: {max_days_overdue} days | Action: {action}"
    )
    logger.info(msg)
