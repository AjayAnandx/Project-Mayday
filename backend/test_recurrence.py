from datetime import datetime

from backend.core import recurrence as rec


def dt(s):
    return datetime.fromisoformat(s)


def test_normalize_legacy_biweekly():
    r = rec.normalize_rule({"pattern": "biweekly", "end_date": "2026-12-31"})
    assert r["freq"] == "weekly" and r["interval"] == 2 and r["until"] == "2026-12-31"


def test_normalize_invalid_returns_none():
    assert rec.normalize_rule(None) is None
    assert rec.normalize_rule({"freq": "hourly"}) is None


def test_weekdays_skip_weekend():
    r = rec.normalize_rule({"freq": "weekdays"})
    fri = dt("2026-11-20T09:00")  # Friday
    assert rec.next_occurrence(fri, r) == dt("2026-11-23T09:00")  # Monday


def test_weekly_byweekday_interval_wraps():
    r = rec.normalize_rule({"freq": "weekly", "interval": 2, "byweekday": [0, 2]})
    wed = dt("2026-11-18T10:00")
    assert rec.next_occurrence(wed, r) == dt("2026-11-30T10:00")  # Monday two weeks on
    mon = dt("2026-11-16T10:00")
    assert rec.next_occurrence(mon, r) == dt("2026-11-18T10:00")


def test_monthly_clamps_short_months():
    r = rec.normalize_rule({"freq": "monthly"})
    assert rec.next_occurrence(dt("2026-01-31T08:00"), r) == dt("2026-02-28T08:00")


def test_monthly_bymonthday_restores_day():
    r = rec.normalize_rule({"freq": "monthly", "bymonthday": 31})
    assert rec.next_occurrence(dt("2026-02-28T08:00"), r) == dt("2026-03-31T08:00")


def test_occurrences_respect_count_and_until():
    r = rec.normalize_rule({"freq": "daily", "count": 3})
    occ = rec.occurrences(dt("2026-11-01T09:00"), r, dt("2026-11-01T00:00"), dt("2026-11-30T00:00"))
    assert len(occ) == 3
    r2 = rec.normalize_rule({"freq": "daily", "until": "2026-11-05"})
    occ2 = rec.occurrences(dt("2026-11-01T09:00"), r2, dt("2026-11-01T00:00"), dt("2026-11-30T00:00"))
    assert occ2[-1].date().isoformat() == "2026-11-05"


def test_occurrences_expand_before_range_filter():
    # series anchored long before the window still yields in-window instances
    r = rec.normalize_rule({"freq": "weekly"})
    occ = rec.occurrences(dt("2026-01-05T10:00"), r, dt("2026-11-16T00:00"), dt("2026-11-22T23:59"))
    assert occ == [dt("2026-11-16T10:00")]


def test_advance_fast_forwards_past_instances():
    r = rec.normalize_rule({"freq": "daily"})
    nxt = rec.advance(dt("2026-11-01T09:00"), r, completed_at=dt("2026-11-18T12:00"))
    assert nxt == dt("2026-11-18T09:00")


def test_advance_from_completion():
    r = rec.normalize_rule({"freq": "daily", "interval": 3, "repeat_from": "completion"})
    nxt = rec.advance(dt("2026-11-01T09:00"), r, completed_at=dt("2026-11-10T18:30"))
    assert nxt == dt("2026-11-13T09:00")


def test_advance_ends_series():
    r = rec.normalize_rule({"freq": "daily", "count": 2})
    assert rec.advance(dt("2026-11-01T09:00"), r, done_count=1) is None


def test_describe():
    assert rec.describe({"freq": "weekly", "byweekday": [0, 4]}) == "every week on Mon, Fri"
