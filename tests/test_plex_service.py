from unittest.mock import MagicMock, patch
import pytest
from plex_service import PlexService

def test_find_user_by_email():
    mock_account = MagicMock()
    user1 = MagicMock()
    user1.email = "alice@example.com"
    user1.username = "alice"

    user2 = MagicMock()
    user2.email = "bob@example.com"
    user2.username = "bob"

    mock_account.users.return_value = [user1, user2]

    service = PlexService(account=mock_account)

    found = service.find_user_by_email("ALICE@example.com ")
    assert found == user1

    not_found = service.find_user_by_email("charlie@example.com")
    assert not_found is None

def test_revoke_user_access_dry_run():
    mock_cfg = MagicMock()
    mock_cfg.PLEX_LIBRARIES = ["Movies"]
    mock_cfg.PLEX_SERVER_NAME = ""

    mock_account = MagicMock()
    user = MagicMock()
    user.email = "alice@example.com"
    mock_account.users.return_value = [user]

    service = PlexService(cfg=mock_cfg, account=mock_account)
    res = service.revoke_user_access("alice@example.com", dry_run=True)

    assert res["found"] is True
    assert res["status"] == "DRY_RUN"
    assert "[DRY-RUN]" in res["action"]

def test_revoke_user_access_not_found():
    mock_account = MagicMock()
    mock_account.users.return_value = []

    service = PlexService(account=mock_account)
    res = service.revoke_user_access("unknown@example.com")

    assert res["found"] is False
    assert res["status"] == "NOT_FOUND"

def test_revoke_user_access_complete_unshare():
    mock_cfg = MagicMock()
    mock_cfg.PLEX_LIBRARIES = []
    
    mock_account = MagicMock()
    user = MagicMock()
    user.email = "bob@example.com"
    mock_account.users.return_value = [user]

    service = PlexService(cfg=mock_cfg, account=mock_account)
    res = service.revoke_user_access("bob@example.com", dry_run=False)

    assert res["found"] is True
    assert res["status"] == "SUCCESS"
    mock_account.removeFriend.assert_called_once_with(user)

def test_revoke_user_access_update_libraries():
    mock_cfg = MagicMock()
    mock_cfg.PLEX_LIBRARIES = ["Movies"]
    mock_cfg.PLEX_SERVER_NAME = "HomeServer"

    mock_account = MagicMock()
    mock_server = MagicMock()
    mock_account.server.return_value = mock_server

    sec1 = MagicMock()
    sec1.title = "Movies"
    sec2 = MagicMock()
    sec2.title = "TV Shows"
    mock_server.library.sections.return_value = [sec1, sec2]

    user = MagicMock()
    user.email = "carol@example.com"
    server_entry = MagicMock()
    sec1_user = MagicMock()
    sec1_user.title = "Movies"
    server_entry.sections.return_value = [sec1_user]
    user.servers = [server_entry]
    mock_account.users.return_value = [user]

    service = PlexService(cfg=mock_cfg, account=mock_account)
    res = service.revoke_user_access("carol@example.com", dry_run=False)

    assert res["found"] is True
    assert res["status"] == "SUCCESS"
    mock_account.updateFriend.assert_called_once_with(user=user, server=mock_server, sections=["TV Shows"])

def test_revoke_user_access_already_disabled():
    mock_cfg = MagicMock()
    mock_cfg.PLEX_LIBRARIES = ["Movies"]

    mock_account = MagicMock()
    user = MagicMock()
    user.email = "carol@example.com"
    server_entry = MagicMock()
    sec2_user = MagicMock()
    sec2_user.title = "TV Shows"
    server_entry.sections.return_value = [sec2_user] # Movies is missing
    user.servers = [server_entry]
    mock_account.users.return_value = [user]

    service = PlexService(cfg=mock_cfg, account=mock_account)
    res = service.revoke_user_access("carol@example.com", dry_run=False)

    assert res["found"] is True
    assert res["status"] == "ALREADY_DISABLED"
    mock_account.updateFriend.assert_not_called()
