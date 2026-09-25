import pytest
from unittest.mock import MagicMock, patch
from main import handle_grant_permanent

def test_handle_grant_permanent_without_name():
    mock_zoho = MagicMock()
    mock_plex = MagicMock()
    mock_plex.grant_user_access.return_value = {"status": "SUCCESS"}
    mock_grant = MagicMock()

    handle_grant_permanent(
        email="testperm@example.com",
        customer_name=None,
        zoho_service=mock_zoho,
        plex_service=mock_plex,
        grant_service=mock_grant,
        dry_run=False
    )

    mock_grant.add_permanent_pass.assert_called_once_with(email="testperm@example.com")
    mock_plex.grant_user_access.assert_called_once_with(email="testperm@example.com", dry_run=False)
    mock_zoho.create_customer.assert_not_called()
    mock_zoho.create_recurring_invoice.assert_not_called()

def test_handle_grant_permanent_with_name():
    mock_zoho = MagicMock()
    mock_zoho.create_customer.return_value = "CUST-999"
    mock_plex = MagicMock()
    mock_plex.grant_user_access.return_value = {"status": "SUCCESS"}
    mock_grant = MagicMock()

    handle_grant_permanent(
        email="testperm2@example.com",
        customer_name="John Permanent",
        zoho_service=mock_zoho,
        plex_service=mock_plex,
        grant_service=mock_grant,
        dry_run=False
    )

    mock_zoho.create_customer.assert_called_once_with(contact_name="John Permanent", email="testperm2@example.com", currency_code="GTQ")
    mock_zoho.create_recurring_invoice.assert_called_once()
    mock_grant.add_permanent_pass.assert_called_once_with(email="testperm2@example.com")
    mock_plex.grant_user_access.assert_called_once_with(email="testperm2@example.com", dry_run=False)
