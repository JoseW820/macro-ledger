from app.analysis.derived import spread, trade_balance
from app.analysis.quality import check_points
from app.analysis.themes import summarize_theme
from app.models import DataPoint


def point(indicator_id, period="2025-08", value=1.0, source="nbs"):
    return DataPoint(indicator_id, indicator_id, period, value, "%", "monthly", source)


def test_quality_checks_duplicate_and_jump_without_blocking():
    report = check_points([point("x", value=1), point("x", value=30), point("x", value=30)])
    assert {issue.code for issue in report.issues} == {"duplicate_period", "abnormal_jump"}


def test_trade_balance_and_spread_are_traceable():
    balance = trade_balance(point("exports", value=10), point("imports", value=4))
    assert balance.value == 6
    assert balance.inputs == ("exports", "imports")
    rate_spread = spread(point("us", value=5), point("cn", value=2), indicator_id="spread")
    assert rate_spread.value == 3


def test_theme_reports_unknown_instead_of_zero():
    result = summarize_theme("需求与收入", {"retail": point("retail", value=2)}, expected=("retail", "income"), positive_when_rising=("retail",))
    assert result.status == "改善"
    assert result.unknown == ("income",)
