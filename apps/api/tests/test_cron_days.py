"""Reading a standard crontab the way standard cron reads it.

APScheduler numbers the week from Monday; cron, `croniter` and every trigger this product
writes number it from Sunday. `app.services.scheduler` translates between the two, and the
cost of getting it wrong is silent: the schedule still fires, one day late, forever.

These tests assert fire times rather than the translated expression, so they stay true if
the translation ever changes shape.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.scheduler import _build_trigger, _cron_days_to_apscheduler

PARIS = "Europe/Paris"
# A Sunday, so a week of fire times starting here visits every day in order.
START = datetime(2026, 9, 13, 0, 0, tzinfo=ZoneInfo("UTC"))


def fire_days(cron: str, count: int, *, timezone: str = PARIS) -> list[str]:
    """The weekday names of the next `count` fires of `cron`, in order."""
    trigger = _build_trigger({"mode": "cron", "cron": cron, "timezone": timezone}, "UTC")
    days: list[str] = []
    moment = START
    for _ in range(count):
        moment = trigger.get_next_fire_time(None, moment)
        assert moment is not None, f"{cron!r} never fires"
        days.append(moment.strftime("%a"))
        moment = moment + timedelta(seconds=1)
    return days


def test_weekday_range_is_monday_to_friday():
    assert fire_days("0 8 * * 1-5", 5) == ["Mon", "Tue", "Wed", "Thu", "Fri"]


def test_zero_is_sunday():
    assert fire_days("0 8 * * 0", 2) == ["Sun", "Sun"]


def test_seven_is_also_sunday():
    assert fire_days("0 8 * * 7", 2) == ["Sun", "Sun"]


def test_six_is_saturday():
    assert fire_days("0 8 * * 6", 1) == ["Sat"]


def test_weekend_list():
    assert fire_days("0 8 * * 0,6", 4) == ["Sun", "Sat", "Sun", "Sat"]


def test_scattered_list():
    assert fire_days("0 8 * * 1,3,5", 3) == ["Mon", "Wed", "Fri"]


def test_names_are_read_as_written():
    assert fire_days("0 8 * * mon-fri", 5) == ["Mon", "Tue", "Wed", "Thu", "Fri"]


def test_step_counts_from_sunday():
    # Standard cron: */2 over 0-6 is Sunday, Tuesday, Thursday, Saturday.
    assert fire_days("0 8 * * */2", 4) == ["Sun", "Tue", "Thu", "Sat"]


def test_range_with_step():
    assert fire_days("0 8 * * 1-5/2", 3) == ["Mon", "Wed", "Fri"]


def test_every_day_still_fires_every_day():
    assert fire_days("0 8 * * *", 7) == ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def test_other_fields_are_untouched():
    trigger = _build_trigger(
        {"mode": "cron", "cron": "30 7 1 3 *", "timezone": PARIS}, "UTC"
    )
    first = trigger.get_next_fire_time(None, START)
    assert first is not None
    assert (first.month, first.day, first.hour, first.minute) == (3, 1, 7, 30)


@pytest.mark.parametrize("field", ["*", "?", ""])
def test_wildcards_stay_wildcards(field):
    assert _cron_days_to_apscheduler(field) == "*"


def test_full_week_collapses_to_a_wildcard():
    assert _cron_days_to_apscheduler("0-6") == "*"


def test_translation_is_ordered_monday_first():
    assert _cron_days_to_apscheduler("6,1,0") == "mon,sat,sun"


@pytest.mark.parametrize("field", ["5-1", "9", "-1", "mon-", "1-5/0", "tomorrow"])
def test_unreadable_fields_are_refused(field):
    with pytest.raises(ValueError):
        _cron_days_to_apscheduler(field)


def test_an_unreadable_day_field_falls_back_to_apscheduler():
    # `5-1` wraps the weekend; we decline to guess, and APScheduler gets the raw crontab
    # so the error the caller sees is its own.
    with pytest.raises(ValueError):
        _build_trigger({"mode": "cron", "cron": "0 8 * * 5-1", "timezone": PARIS}, "UTC")


def test_interval_mode_is_unaffected():
    trigger = _build_trigger({"mode": "interval", "every_minutes": 15}, PARIS)
    assert trigger.interval == timedelta(minutes=15)
