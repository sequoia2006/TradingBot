import sys
from datetime import datetime, time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.brokers import PaperBroker  # noqa: E402
from bot.config import Settings  # noqa: E402
from bot.executor import Executor  # noqa: E402
from bot.risk import NY, RiskManager  # noqa: E402

SECRET = "test-secret-123456"
# A Tuesday, 10:30 New York time
NOW = datetime(2026, 11, 3, 10, 30, tzinfo=NY)


@pytest.fixture
def settings():
    return Settings(webhook_secret=SECRET, admin_token="admin-tok", contract="MNQZ6",
                    entry_window=(time(9, 35), time(15, 45)), max_signal_age_sec=0)


@pytest.fixture
def clock():
    state = {"now": NOW}
    f = lambda: state["now"]  # noqa: E731
    f.state = state
    return f


@pytest.fixture
def executor(settings, clock):
    return Executor(settings, PaperBroker(commission_per_side=0), RiskManager(settings, clock))


def sig(action, **kw):
    from bot.models import Signal
    base = {"secret": SECRET, "action": action, "qty": 1, "price": 20000.0}
    base.update(kw)
    return Signal(**base)
