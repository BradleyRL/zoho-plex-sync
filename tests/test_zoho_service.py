from datetime import date
from unittest.mock import MagicMock, patch
import pytest
from zoho_service import ZohoBooksService

def test_calculate_days_overdue():
    ref_date = date(2026, 9, 23)

    # 4 days overdue -> > 3 days
    assert ZohoBooksService.calculate_days_overdue("2026-09-19", reference_date=ref_date) == 4

    # 3 days overdue -> equal to 3 days (not > 3)
    assert ZohoBooksService.calculate_days_overdue("2026-09-20", reference_date=ref_date) == 3

    # 1 day overdue
    assert ZohoBooksService.calculate_days_overdue("2026-09-22", reference_date=ref_date) == 1

def test_get_users_to_disable_filters_threshold():
    mock_cfg = MagicMock()
    mock_cfg.OVERDUE_DAYS_THRESHOLD = 3

    service = ZohoBooksService(cfg=mock_cfg)

    # Mock invoices response from Zoho
    mock_invoices = [
        {
            "invoice_number": "INV-001",
            "due_date": "2026-09-15", # 8 days overdue
            "email": "user1@example.com",
            "customer_name": "User One",
            "customer_id": "101"
        },
        {
            "invoice_number": "INV-002",
            "due_date": "2026-09-20", # 3 days overdue (should be skipped since threshold is 3)
            "email": "user2@example.com",
            "customer_name": "User Two",
            "customer_id": "102"
        },
        {
            "invoice_number": "INV-003",
            "due_date": "2026-09-18", # 5 days overdue
            "email": "user1@example.com", # Same user as INV-001
            "customer_name": "User One",
            "customer_id": "101"
        }
    ]

    with patch.object(service, 'get_overdue_invoices', return_value=mock_invoices):
        ref_date = date(2026, 9, 23)
        result = service.get_users_to_disable(days_threshold=3, reference_date=ref_date)

        # Only user1 should be returned, with 2 invoices aggregated
        assert len(result) == 1
        u1 = result[0]
        assert u1["email"] == "user1@example.com"
        assert sorted(u1["invoice_numbers"]) == ["INV-001", "INV-003"]
        assert u1["max_days_overdue"] == 8

def test_get_active_recurring_invoice_emails():
    mock_cfg = MagicMock()
    service = ZohoBooksService(cfg=mock_cfg)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "code": 0,
        "recurring_invoices": [
            {"email": "active1@example.com", "status": "active"},
            {"email": "ACTIVE2@EXAMPLE.COM ", "status": "active"}
        ],
        "page_context": {"has_more_page": False}
    }

    with patch("requests.get", return_value=mock_resp):
        with patch.object(service, "get_headers", return_value={}):
            emails = service.get_active_recurring_invoice_emails()
            assert emails == {"active1@example.com", "active2@example.com"}
