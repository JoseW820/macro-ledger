import json
from pathlib import Path

from app.models import DataPoint, IndicatorDefinition
from app.storage.sqlite import SQLiteStore
from app.web import _upload_json


def _definition() -> IndicatorDefinition:
    return IndicatorDefinition(
        indicator_id="cpi_yoy",
        name="居民消费价格指数同比",
        theme="prices",
        frequency="monthly",
        unit="%",
        value_type="yoy",
        primary_source="nbs",
    )


def _artifact(store: SQLiteStore, root: Path, artifact_id: int, vintage: str, value: float) -> None:
    normalized = root / f"normalized-{artifact_id}.json"
    normalized.write_text(json.dumps([{"retrieved_at": vintage, "value": value}]), encoding="utf-8")
    raw = root / f"raw-{artifact_id}.json"
    raw.write_text("{}", encoding="utf-8")
    metadata = {"normalized_artifact": str(normalized), "source_file": str(root / f"incoming-{artifact_id}.json")}
    store.connection.execute(
        "INSERT INTO raw_artifacts(artifact_id, source, indicator_id, period, path, sha256, retrieved_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (artifact_id, "web_upload", "cpi_yoy", "2026-07", str(raw), f"hash-{artifact_id}", "2026-09-25 04:00:00", json.dumps(metadata)),
    )
    store.connection.commit()


def test_uploads_mark_duplicate_versions_and_delete_one_vintage(tmp_path: Path):
    store = SQLiteStore(tmp_path / "macro.sqlite")
    definition = _definition()
    store.upsert_definition(definition, updated_at="2026-09-25")
    first_vintage = "2026-09-25T04:00:00+00:00"
    second_vintage = "2026-09-25T04:05:00+00:00"
    store.insert_points([DataPoint("cpi_yoy", definition.name, "2026-07", 0.2, "%", "monthly", "nbs", retrieved_at=first_vintage)])
    store.insert_points([DataPoint("cpi_yoy", definition.name, "2026-07", 0.3, "%", "monthly", "nbs", retrieved_at=second_vintage)])
    _artifact(store, tmp_path, 1, first_vintage, 0.2)
    _artifact(store, tmp_path, 2, second_vintage, 0.3)

    rows = store.uploads(period="2026-07")
    assert len(rows) == 2
    assert {row["duplicate_count"] for row in rows} == {2}
    assert [row["artifact_id"] for row in store.duplicate_uploads(period="2026-07")] == [1]
    assert _upload_json(rows[0], store)["value"] in {0.2, 0.3}

    deleted = store.delete_upload(1, vintage=first_vintage)
    assert deleted and deleted["deleted_observations"] == 1
    assert store.connection.execute("SELECT count(*) FROM raw_artifacts").fetchone()[0] == 1
    assert store.connection.execute("SELECT count(*) FROM observations WHERE vintage=?", (first_vintage,)).fetchone()[0] == 0
    assert store.connection.execute("SELECT count(*) FROM observations WHERE vintage=?", (second_vintage,)).fetchone()[0] == 1
    store.close()
