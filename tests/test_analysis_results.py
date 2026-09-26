import json
from pathlib import Path

from app.storage.sqlite import SQLiteStore


def test_analysis_versions_and_confirmation(tmp_path: Path):
    store = SQLiteStore(tmp_path / "macro.sqlite")
    first = store.save_analysis(period="2026-07", package_id="pkg", result={"period": "2026-07", "overview": "一"}, markdown=None, warnings=[])
    second = store.save_analysis(period="2026-07", package_id="pkg", result={"period": "2026-07", "overview": "二"}, markdown="# 二", warnings=["引用需复核"])
    assert [row["version"] for row in store.analyses(period="2026-07")] == [2, 1]
    confirmed = store.confirm_analysis(second)
    assert confirmed["status"] == "confirmed"
    assert store.analysis(first)["status"] == "draft"
    assert json.loads(confirmed["warnings_json"]) == ["引用需复核"]
    store.close()
