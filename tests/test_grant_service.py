from datetime import datetime, timedelta
import pytest
from grant_service import GrantService

def test_temporary_pass_lifecycle(tmp_path):
    data_file = tmp_path / "grants.json"
    service = GrantService(file_path=data_file)

    now = datetime(2026, 9, 23, 10, 0, 0)
    
    # 1. Add 2-day temporary pass
    pass_info = service.add_temporary_pass("tempuser@example.com", days=2, reference_time=now)
    assert pass_info["days"] == 2

    # 2. Active at 1 day after
    day1 = now + timedelta(days=1)
    assert service.is_temporary_active("tempuser@example.com", reference_time=day1) is True

    # 3. Expired at 2 days + 1 min after
    expired_time = now + timedelta(days=2, minutes=1)
    assert service.is_temporary_active("tempuser@example.com", reference_time=expired_time) is False

    # 4. Get expired passes triggers revocation list & auto cleanup
    expired_list = service.get_expired_temporary_passes(reference_time=expired_time)
    assert expired_list == ["tempuser@example.com"]

    # 5. Second check after cleanup returns empty list
    expired_list_2 = service.get_expired_temporary_passes(reference_time=expired_time)
    assert expired_list_2 == []

def test_permanent_pass_lifecycle(tmp_path):
    data_file = tmp_path / "grants.json"
    service = GrantService(file_path=data_file)

    service.add_permanent_pass("vip@example.com")
    assert service.is_permanently_allowed("vip@example.com") is True
    assert service.is_permanently_allowed("normal@example.com") is False

def test_upgrade_temp_to_permanent(tmp_path):
    data_file = tmp_path / "grants.json"
    service = GrantService(file_path=data_file)

    service.add_temporary_pass("user@example.com", days=2)
    assert service.is_temporary_active("user@example.com") is True

    # Upgrade to permanent
    service.add_permanent_pass("user@example.com")
    assert service.is_permanently_allowed("user@example.com") is True
    assert service.is_temporary_active("user@example.com") is False
