"""Quarter-hour market monitoring cannot masquerade as extra forward fills."""
from datetime import datetime, timedelta, timezone
import pytest

from aegis.forward_broker import _monitor_slot_id


def test_same_quarter_is_idempotent():
    first = datetime(2026,10,8,10,20,0,tzinfo=timezone.utc)
    assert _monitor_slot_id(first) == _monitor_slot_id(first+timedelta(minutes=5))
    assert _monitor_slot_id(first) != _monitor_slot_id(first+timedelta(minutes=15))


def test_slots_unique_across_utc_hour_boundary():
    first = datetime(2026,10,8,10,50,0,tzinfo=timezone.utc)
    second = datetime(2026,10,8,11,5,0,tzinfo=timezone.utc)
    assert _monitor_slot_id(first) != _monitor_slot_id(second)


def test_reject_ambiguous_naive_time():
    with pytest.raises(ValueError,match="timezone-aware"):
        _monitor_slot_id(datetime(2026,10,8,10,5))
