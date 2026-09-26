"""SQLite history store with immutable vintage-aware observations."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from app.models import DataPoint, FetchResult, IndicatorDefinition, QualityIssue


SCHEMA = """
CREATE TABLE IF NOT EXISTS indicator_definitions (
  indicator_id TEXT PRIMARY KEY, name TEXT NOT NULL, theme TEXT NOT NULL,
  frequency TEXT NOT NULL, unit TEXT NOT NULL, value_type TEXT NOT NULL,
  primary_source TEXT NOT NULL, definition_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS observations (
  indicator_id TEXT NOT NULL, period TEXT NOT NULL, vintage TEXT NOT NULL,
  value TEXT, unit TEXT NOT NULL, frequency TEXT NOT NULL, source TEXT NOT NULL,
  source_url TEXT, release_date TEXT, retrieved_at TEXT NOT NULL, definition TEXT,
  calculation_method TEXT, revision_status TEXT NOT NULL, quality_status TEXT NOT NULL,
  PRIMARY KEY (indicator_id, period, vintage)
);
CREATE TABLE IF NOT EXISTS raw_artifacts (
  artifact_id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
  indicator_id TEXT, period TEXT, path TEXT NOT NULL, sha256 TEXT,
  source_url TEXT, release_date TEXT, retrieved_at TEXT NOT NULL, metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_releases (
  source TEXT NOT NULL, release_date TEXT NOT NULL, source_url TEXT NOT NULL,
  sha256 TEXT, retrieved_at TEXT NOT NULL, metadata_json TEXT NOT NULL,
  PRIMARY KEY (source, release_date, source_url)
);
CREATE TABLE IF NOT EXISTS quality_issues (
  issue_id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, message TEXT NOT NULL,
  indicator_id TEXT, period TEXT, severity TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_history (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, period TEXT NOT NULL, started_at TEXT NOT NULL,
  finished_at TEXT, provider TEXT, status TEXT NOT NULL, summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
  indicator_id TEXT NOT NULL, period TEXT NOT NULL, vintage TEXT NOT NULL,
  previous_vintage TEXT, reason TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY (indicator_id, period, vintage)
);
CREATE TABLE IF NOT EXISTS analysis_results (
  analysis_id INTEGER PRIMARY KEY AUTOINCREMENT,
  period TEXT NOT NULL,
  package_id TEXT,
  version INTEGER NOT NULL,
  status TEXT NOT NULL,
  result_json TEXT NOT NULL,
  result_markdown TEXT,
  warnings_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  confirmed_at TEXT,
  UNIQUE(period, version)
);
CREATE INDEX IF NOT EXISTS idx_observations_theme_source ON observations(source, frequency);
"""


class SQLiteStore:
    def __init__(self, path: Path | str = Path("data/macro_observer.sqlite")) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def upsert_definition(self, indicator: IndicatorDefinition, *, updated_at: str) -> None:
        self.connection.execute(
            """INSERT INTO indicator_definitions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(indicator_id) DO UPDATE SET name=excluded.name, theme=excluded.theme,
            frequency=excluded.frequency, unit=excluded.unit, value_type=excluded.value_type,
            primary_source=excluded.primary_source, definition_json=excluded.definition_json,
            updated_at=excluded.updated_at""",
            (indicator.indicator_id, indicator.name, indicator.theme, indicator.frequency, indicator.unit, indicator.value_type, indicator.primary_source, json.dumps(asdict(indicator), ensure_ascii=False), updated_at),
        )
        self.connection.commit()

    def insert_points(self, points: Iterable[DataPoint], *, vintage: str | None = None, reason: str | None = None) -> int:
        rows = list(points)
        count = 0
        for point in rows:
            current_vintage = vintage or point.retrieved_at
            previous = self.connection.execute("SELECT vintage FROM observations WHERE indicator_id=? AND period=? ORDER BY vintage DESC LIMIT 1", (point.indicator_id, point.period)).fetchone()
            self.connection.execute(
                "INSERT OR IGNORE INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (point.indicator_id, point.period, current_vintage, json.dumps(point.value, ensure_ascii=False), point.unit, point.frequency, point.source, point.source_url, point.release_date, point.retrieved_at, point.definition, point.calculation_method, point.revision_status, point.quality_status),
            )
            if previous and previous["vintage"] != current_vintage:
                self.connection.execute("INSERT OR IGNORE INTO revisions VALUES (?, ?, ?, ?, ?, datetime('now'))", (point.indicator_id, point.period, current_vintage, previous["vintage"], reason or "new_vintage"))
            count += 1
        self.connection.commit()
        return count

    def insert_fetch_result(self, result: FetchResult, *, provider: str | None = None) -> None:
        self.insert_points(result.points)
        if result.raw_artifact:
            self.connection.execute("INSERT INTO raw_artifacts(source, indicator_id, period, path, sha256, source_url, release_date, retrieved_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)", (provider or result.points[0].source if result.points else "unknown", result.indicator.indicator_id, result.period, result.raw_artifact, result.metadata.get("sha256"), result.metadata.get("source_url"), result.metadata.get("release_date"), json.dumps(result.metadata, ensure_ascii=False)))
        self.connection.commit()

    def insert_issue(self, issue: QualityIssue) -> None:
        self.connection.execute("INSERT INTO quality_issues(code, message, indicator_id, period, severity, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))", (issue.code, issue.message, issue.indicator_id, issue.period, issue.severity))
        self.connection.commit()

    def latest(self, indicator_id: str, period: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM observations WHERE indicator_id=? AND period=? ORDER BY vintage DESC LIMIT 1", (indicator_id, period)).fetchone()

    def uploads(self, *, period: str | None = None) -> list[sqlite3.Row]:
        """Return imported raw artifacts, including duplicate counts per series."""
        query = """
            SELECT r.*, d.name AS indicator_name, d.unit AS indicator_unit,
                   COUNT(*) OVER (PARTITION BY r.indicator_id, r.period) AS duplicate_count
            FROM raw_artifacts r
            LEFT JOIN indicator_definitions d ON d.indicator_id = r.indicator_id
            WHERE 1=1
        """
        args: list[str] = []
        if period:
            query += " AND r.period=?"
            args.append(period)
        query += " ORDER BY r.period DESC, r.indicator_id, r.artifact_id DESC"
        return list(self.connection.execute(query, args))

    def duplicate_uploads(self, *, period: str | None = None) -> list[sqlite3.Row]:
        """Return older artifacts, keeping the latest import for each series."""
        rows = self.uploads(period=period)
        seen: set[tuple[str | None, str | None]] = set()
        duplicates: list[sqlite3.Row] = []
        for row in rows:  # uploads() is newest-first within each series
            key = (row["indicator_id"], row["period"])
            if key in seen:
                duplicates.append(row)
            else:
                seen.add(key)
        return duplicates

    def upload(self, artifact_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            """SELECT r.*, d.name AS indicator_name, d.unit AS indicator_unit
               FROM raw_artifacts r LEFT JOIN indicator_definitions d
               ON d.indicator_id=r.indicator_id WHERE r.artifact_id=?""",
            (artifact_id,),
        ).fetchone()

    def delete_upload(self, artifact_id: int, *, vintage: str | None = None) -> dict[str, object] | None:
        """Delete one imported artifact and only its matching observation version.

        The caller supplies the version timestamp read from the normalized artifact.
        Related revision rows are removed or detached, while other vintages remain.
        """
        row = self.upload(artifact_id)
        if row is None:
            return None
        indicator_id = row["indicator_id"]
        period = row["period"]
        deleted_observations = 0
        deleted_revisions = 0
        with self.connection:
            if vintage:
                cursor = self.connection.execute(
                    "DELETE FROM observations WHERE indicator_id=? AND period=? AND vintage=?",
                    (indicator_id, period, vintage),
                )
                deleted_observations = cursor.rowcount
                cursor = self.connection.execute(
                    "DELETE FROM revisions WHERE indicator_id=? AND period=? AND vintage=?",
                    (indicator_id, period, vintage),
                )
                deleted_revisions = cursor.rowcount
                self.connection.execute(
                    "UPDATE revisions SET previous_vintage=NULL WHERE indicator_id=? AND period=? AND previous_vintage=?",
                    (indicator_id, period, vintage),
                )
            self.connection.execute("DELETE FROM raw_artifacts WHERE artifact_id=?", (artifact_id,))
        return {
            "artifact_id": artifact_id,
            "indicator_id": indicator_id,
            "period": period,
            "vintage": vintage,
            "deleted_observations": deleted_observations,
            "deleted_revisions": deleted_revisions,
        }

    def history(self, *, source: str | None = None, frequency: str | None = None, theme: str | None = None) -> list[sqlite3.Row]:
        query = "SELECT o.*, d.theme FROM observations o LEFT JOIN indicator_definitions d ON d.indicator_id=o.indicator_id WHERE 1=1"
        args: list[str] = []
        if source:
            query += " AND o.source=?"; args.append(source)
        if frequency:
            query += " AND o.frequency=?"; args.append(frequency)
        if theme:
            query += " AND d.theme=?"; args.append(theme)
        return list(self.connection.execute(query + " ORDER BY o.period, o.indicator_id, o.vintage", args))

    def run_start(self, period: str, provider: str | None = None, *, started_at: str | None = None) -> int:
        cursor = self.connection.execute(
            "INSERT INTO run_history(period, started_at, provider, status, summary_json) VALUES (?, COALESCE(?, datetime('now')), ?, ?, ?)",
            (period, started_at, provider, "running", "{}"),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def run_finish(self, run_id: int, *, status: str, summary: dict, finished_at: str | None = None) -> None:
        self.connection.execute(
            "UPDATE run_history SET finished_at=COALESCE(?, datetime('now')), status=?, summary_json=? WHERE run_id=?",
            (finished_at, status, json.dumps(summary, ensure_ascii=False), run_id),
        )
        self.connection.commit()

    def runs(self, *, period: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
        if period:
            return list(self.connection.execute("SELECT * FROM run_history WHERE period=? ORDER BY run_id DESC LIMIT ?", (period, limit)))
        return list(self.connection.execute("SELECT * FROM run_history ORDER BY run_id DESC LIMIT ?", (limit,)))

    def save_analysis(self, *, period: str, package_id: str | None, result: dict, markdown: str | None, warnings: list[str], status: str = "draft") -> int:
        row = self.connection.execute("SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM analysis_results WHERE period=?", (period,)).fetchone()
        version = int(row["next_version"])
        cursor = self.connection.execute(
            "INSERT INTO analysis_results(period, package_id, version, status, result_json, result_markdown, warnings_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (period, package_id, version, status, json.dumps(result, ensure_ascii=False), markdown, json.dumps(warnings, ensure_ascii=False)),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def analyses(self, *, period: str | None = None) -> list[sqlite3.Row]:
        if period:
            return list(self.connection.execute("SELECT * FROM analysis_results WHERE period=? ORDER BY version DESC", (period,)))
        return list(self.connection.execute("SELECT * FROM analysis_results ORDER BY period DESC, version DESC"))

    def analysis(self, analysis_id: int) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM analysis_results WHERE analysis_id=?", (analysis_id,)).fetchone()

    def confirm_analysis(self, analysis_id: int) -> sqlite3.Row | None:
        row = self.analysis(analysis_id)
        if row is None:
            return None
        with self.connection:
            self.connection.execute("UPDATE analysis_results SET status='archived' WHERE period=? AND status='confirmed'", (row["period"],))
            self.connection.execute("UPDATE analysis_results SET status='confirmed', confirmed_at=datetime('now') WHERE analysis_id=?", (analysis_id,))
        return self.analysis(analysis_id)
