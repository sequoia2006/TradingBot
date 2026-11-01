from datetime import date

from bot.contracts import front_month, third_friday


def test_third_friday():
    assert third_friday(2026, 12) == date(2026, 12, 18)
    assert third_friday(2027, 3) == date(2027, 3, 19)


def test_front_month_and_roll():
    assert front_month("MNQ", date(2026, 11, 1)) == "MNQZ6"
    assert front_month("MNQ", date(2026, 12, 9)) == "MNQZ6"
    assert front_month("MNQ", date(2026, 12, 10)) == "MNQH7"  # 8 days before 12/18
    assert front_month("MNQ", date(2027, 1, 15)) == "MNQH7"
