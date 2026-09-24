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
        with patch.object(service, 'fetch_all_contact_emails', return_value=[]):
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
            {"email": "active1@example.com", "customer_id": "C101", "status": "active"},
            {"email": "ACTIVE2@EXAMPLE.COM ", "customer_id": "C102", "status": "active"}
        ],
        "page_context": {"has_more_page": False}
    }

    def mock_contact_emails(customer_id):
        if customer_id == "C101":
            return ["active1@example.com", "secondary_c101@example.com"]
        return ["active2@example.com"]

    with patch("requests.get", return_value=mock_resp):
        with patch.object(service, "get_headers", return_value={}):
            with patch.object(service, "fetch_all_contact_emails", side_effect=mock_contact_emails):
                emails = service.get_active_recurring_invoice_emails()
                assert emails == {"active1@example.com", "active2@example.com", "secondary_c101@example.com"}

def test_void_invoice():
    mock_cfg = MagicMock()
    mock_cfg.ZOHO_BOOKS_API_URL = "https://zohoapis.com/books/v3"
    mock_cfg.ZOHO_ORGANIZATION_ID = "org123"
    service = ZohoBooksService(cfg=mock_cfg)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"code": 0, "message": "The invoice has been marked as void."}'
    mock_resp.json.return_value = {"code": 0, "message": "The invoice has been marked as void."}

    with patch("requests.post", return_value=mock_resp) as mock_post:
        with patch.object(service, "get_headers", return_value={"Authorization": "Bearer token"}):
            res = service.void_invoice("inv_999", reason="No Renovó")
            assert res["code"] == 0
            mock_post.assert_called_once_with(
                "https://zohoapis.com/books/v3/invoices/inv_999/status/void",
                headers={"Authorization": "Bearer token"},
                params={"organization_id": "org123", "reason": "No Renovó"},
                json={"reason": "No Renovó"},
                timeout=30
            )

def test_stop_recurring_invoices_for_customer():
    mock_cfg = MagicMock()
    mock_cfg.ZOHO_BOOKS_API_URL = "https://zohoapis.com/books/v3"
    mock_cfg.ZOHO_ORGANIZATION_ID = "org123"
    service = ZohoBooksService(cfg=mock_cfg)

    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.json.return_value = {
        "code": 0,
        "recurring_invoices": [
            {"recurring_invoice_id": "rec_100", "recurring_invoice_number": "REC-100", "status": "active"}
        ]
    }

    stop_resp = MagicMock()
    stop_resp.status_code = 200
    stop_resp.content = b'{"code": 0, "message": "Stopped"}'
    stop_resp.json.return_value = {"code": 0, "message": "Stopped"}

    with patch("requests.get", return_value=search_resp) as mock_get:
        with patch("requests.post", return_value=stop_resp) as mock_post:
            with patch.object(service, "get_headers", return_value={"Authorization": "Bearer token"}):
                stopped = service.stop_recurring_invoices_for_customer("cust_123")
                assert len(stopped) == 1
                assert stopped[0]["recurring_invoice_id"] == "rec_100"
                mock_post.assert_called_once_with(
                    "https://zohoapis.com/books/v3/recurringinvoices/rec_100/status/stop",
                    headers={"Authorization": "Bearer token"},
                    params={"organization_id": "org123"},
                    timeout=30
                )
