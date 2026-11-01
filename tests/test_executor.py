from datetime import datetime

from conftest import NY, sig


def test_long_then_flat_realizes_pnl(executor):
    r = executor.handle(sig("long", stop=19980, target=20040))
    assert r["status"] == "filled" and executor.broker.position("MNQZ6") == 1
    r = executor.handle(sig("flat", price=20010.0))
    assert r["status"] == "filled" and executor.broker.position("MNQZ6") == 0
    assert executor.broker.daily_pnl() == 20.0  # 10 pts * $2


def test_reversal(executor):
    executor.handle(sig("long"))
    r = executor.handle(sig("short", price=19990.0))
    assert r["status"] == "filled" and r["from"] == 1
    assert executor.broker.position("MNQZ6") == -1


def test_same_side_is_noop(executor):
    executor.handle(sig("long"))
    assert executor.handle(sig("long"))["status"] == "noop"
    assert executor.broker.position("MNQZ6") == 1


def test_duplicate_signal_ignored(executor):
    executor.handle(sig("long", signal_id="abc"))
    executor.handle(sig("flat", signal_id="x"))
    assert executor.handle(sig("long", signal_id="abc"))["status"] == "ignored"
    assert executor.broker.position("MNQZ6") == 0


def test_outside_window_rejects_entry_but_allows_exit(executor, clock):
    executor.handle(sig("long"))
    clock.state["now"] = datetime(2026, 11, 3, 16, 30, tzinfo=NY)
    assert executor.handle(sig("short"))["status"] == "partial"  # closed long, no new short
    assert executor.broker.position("MNQZ6") == 0
    assert executor.handle(sig("long"))["status"] == "rejected"


def test_weekend_rejected(executor, clock):
    clock.state["now"] = datetime(2026, 11, 1, 10, 30, tzinfo=NY)
    assert executor.handle(sig("long"))["status"] == "rejected"


def test_max_contracts(executor):
    r = executor.handle(sig("long", qty=5))
    assert r["status"] == "rejected" and "MAX_CONTRACTS" in r["reason"]


def test_max_trades_per_day(executor, settings):
    settings.max_trades_per_day = 2
    executor.handle(sig("long"))
    executor.handle(sig("short"))
    executor.handle(sig("flat"))
    assert executor.handle(sig("long"))["status"] == "rejected"


def test_daily_loss_limit_engages_kill(executor, settings):
    settings.daily_loss_limit = 50
    executor.handle(sig("long", price=20000.0))
    executor.handle(sig("flat", price=19970.0))  # -$60
    r = executor.handle(sig("long"))
    assert r["status"] == "rejected" and executor.risk.killed


def test_stale_signal(executor, settings):
    settings.max_signal_age_sec = 30
    old = int(datetime(2026, 11, 3, 10, 29, tzinfo=NY).timestamp() * 1000)
    assert executor.handle(sig("long", sent_at=old))["status"] == "rejected"


def test_bad_stop_side(executor):
    assert executor.handle(sig("long", stop=20010))["status"] == "rejected"


def test_wrong_symbol(executor):
    assert executor.handle(sig("long", symbol="ES"))["status"] == "rejected"
