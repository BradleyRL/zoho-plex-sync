from unittest.mock import patch, MagicMock
import pytest
from discord_notifier import send_discord_sync_summary

def test_send_discord_sync_summary_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    summary_data = {
        "dry_run": False,
        "threshold": 3,
        "expired_processed": [
            {"email": "temp@example.com", "customer": "Temp", "status": "SUCCESS", "rec_invoice": "Creada exitosamente"}
        ],
        "summary": {
            "total": 1,
            "success": 1,
            "already_disabled": 0,
            "not_found": 0,
            "failed": 0
        }
    }

    with patch("discord_notifier.config") as mock_cfg:
        mock_cfg.DISCORD_WEBHOOK_URL = ""
        mock_cfg.DISCORD_BOT_TOKEN = "test_token"
        mock_cfg.DISCORD_NOTIFICATION_CHANNEL_ID = "1552699204772696267"
        mock_cfg.OVERDUE_DAYS_THRESHOLD = 3

        with patch("requests.post", return_value=mock_resp) as mock_post:
            res = send_discord_sync_summary(summary_data)
            assert res is True
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert "1552699204772696267" in args[0]
            assert kwargs["headers"]["Authorization"] == "Bot test_token"
            assert len(kwargs["json"]["embeds"]) == 1

def test_send_discord_sync_summary_webhook():
    mock_resp = MagicMock()
    mock_resp.status_code = 204

    summary_data = {
        "dry_run": False,
        "threshold": 3,
        "summary": {"total": 0, "success": 0, "already_disabled": 0, "not_found": 0, "failed": 0}
    }

    with patch("discord_notifier.config") as mock_cfg:
        mock_cfg.DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/123/abc"
        mock_cfg.DISCORD_BOT_TOKEN = ""
        mock_cfg.DISCORD_NOTIFICATION_CHANNEL_ID = ""
        mock_cfg.OVERDUE_DAYS_THRESHOLD = 3

        with patch("requests.post", return_value=mock_resp) as mock_post:
            res = send_discord_sync_summary(summary_data)
            assert res is True
            mock_post.assert_called_once_with(
                "https://discord.com/api/webhooks/123/abc",
                json=pytest.any_int if False else mock_post.call_args[1]["json"],
                timeout=15
            )

def test_send_discord_sync_summary_no_token():
    with patch("discord_notifier.config") as mock_cfg:
        mock_cfg.DISCORD_WEBHOOK_URL = ""
        mock_cfg.DISCORD_BOT_TOKEN = ""
        mock_cfg.DISCORD_NOTIFICATION_CHANNEL_ID = "1552699204772696267"

        res = send_discord_sync_summary({})
        assert res is False
