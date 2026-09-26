import pytest

from app.pipeline.normalize import NormalizationError, PeriodMismatchError, normalize_period, period_to_api_code


def test_monthly_period_conversion():
    assert normalize_period("2025年8月", "monthly") == "2025-08"
    assert normalize_period("202508", "monthly") == "2025-08"
    assert period_to_api_code("2025-08", "monthly") == "202508"


def test_quarterly_and_annual_period_conversion():
    assert normalize_period("2025年第2季度", "quarterly") == "2025-Q2"
    assert normalize_period("2026年第二季度", "quarterly") == "2026-Q2"
    assert normalize_period("202602", "quarterly") == "2026-Q2"
    assert normalize_period("2025Q4", "quarterly") == "2025-Q4"
    assert normalize_period("2025年", "annual") == "2025"
    assert period_to_api_code("2025-Q2", "quarterly") == "2025Q2"


def test_combined_january_february_release_is_not_split():
    with pytest.raises(PeriodMismatchError):
        normalize_period("2025年1—2月", "monthly")


def test_unknown_period_is_rejected():
    with pytest.raises(NormalizationError):
        normalize_period("2025-W01", "monthly")
