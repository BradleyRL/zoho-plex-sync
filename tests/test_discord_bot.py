import pytest
from unittest.mock import patch, MagicMock
from discord_bot import is_authorized, check_auth_or_embed

def test_is_authorized_empty_list():
    with patch("discord_bot.config") as mock_config:
        mock_config.DISCORD_ALLOWED_USERS = []
        assert is_authorized(12345) is True

def test_is_authorized_with_allowed_user():
    with patch("discord_bot.config") as mock_config:
        mock_config.DISCORD_ALLOWED_USERS = [12345, 67890]
        assert is_authorized(12345) is True
        assert is_authorized(99999) is False

def test_check_auth_or_embed_unauthorized():
    interaction = MagicMock()
    interaction.user.id = 99999

    with patch("discord_bot.config") as mock_config:
        mock_config.DISCORD_ALLOWED_USERS = [12345]
        embed = check_auth_or_embed(interaction)
        assert embed is not None
        assert "Acceso No Autorizado" in embed.title
