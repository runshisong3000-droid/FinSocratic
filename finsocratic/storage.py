"""Small persistent research workspace for the local FinSocratic application.

The database contains user-imported structured data, extracted document text and
completed audit runs.  Raw uploaded documents are not silently copied to disk.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .data import SAMPLE_DIR, WORKSPACE, fund_metrics, load_samples
from .library import extract_document, retrieve


def json_safe(value: Any) -> Any:
    """Convert pandas/NumPy values and non-finite numbers to strict JSON values."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, (np.integer, np.floating)):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_name(name: str) -> str:
    return Path(str(name).replace("\\", "/")).name[:200] or "unnamed"


def _iso_date(value: Any) -> str | None:
    if isinstance(value, (int, float, np.number)) and not isinstance(value, bool):
        number = float(value)
        if math.isfinite(number) and number.is_integer() and 19000101 <= number <= 21001231:
            parsed = pd.to_datetime(str(int(number)), format="%Y%m%d", errors="coerce")
        else:
            return None
    else:
        parsed = pd.to_datetime(value, errors="coerce")
    return parsed.date().isoformat() if pd.notna(parsed) else None


class WorkspaceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path or (WORKSPACE / "research.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._analytics_cache = {}
        self._create_tables()
        self._seed_samples()
        self._seed_optional_assets()
        self._backfill_run_tasks()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _create_tables(self) -> None:
        with self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS funds (
                    fund_id TEXT PRIMARY KEY, name TEXT NOT NULL, manager TEXT NOT NULL,
                    strategy TEXT NOT NULL, details_json TEXT NOT NULL, is_sample INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS nav (
                    fund_id TEXT NOT NULL, date TEXT NOT NULL, nav REAL NOT NULL,
                    source_file TEXT NOT NULL, source_row INTEGER,
                    PRIMARY KEY (fund_id, date), FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
                );
                CREATE TABLE IF NOT EXISTS holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, fund_id TEXT NOT NULL,
                    asset TEXT NOT NULL, weight_pct REAL NOT NULL, as_of TEXT NOT NULL,
                    source_file TEXT NOT NULL, source_row INTEGER,
                    FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
                );
                CREATE INDEX IF NOT EXISTS idx_holdings_fund_date ON holdings(fund_id, as_of);
                CREATE TABLE IF NOT EXISTS fof_holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, fund_id TEXT NOT NULL,
                    target_code TEXT NOT NULL, target_name TEXT NOT NULL,
                    weight_pct REAL NOT NULL, report_date TEXT NOT NULL,
                    source_file TEXT NOT NULL, source_row INTEGER,
                    FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
                );
                CREATE INDEX IF NOT EXISTS idx_fof_holdings_fund_date ON fof_holdings(fund_id, report_date);
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, fund_id TEXT NOT NULL, period TEXT NOT NULL,
                    name TEXT NOT NULL, sha256 TEXT NOT NULL, added_at TEXT NOT NULL,
                    chunks_json TEXT NOT NULL, is_sample INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
                );
                CREATE INDEX IF NOT EXISTS idx_documents_fund ON documents(fund_id, added_at);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, fund_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    result_json TEXT NOT NULL, input_json TEXT NOT NULL,
                    FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
                );
                CREATE INDEX IF NOT EXISTS idx_runs_fund_date ON runs(fund_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS research_tasks (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, fund_id TEXT NOT NULL,
                    question_key TEXT NOT NULL, question TEXT NOT NULL, priority TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open', category TEXT NOT NULL,
                    related_claim_ids_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, resolution_note TEXT NOT NULL DEFAULT '',
                    UNIQUE(run_id, question_key),
                    FOREIGN KEY (run_id) REFERENCES runs(id),
                    FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_fund_status ON research_tasks(fund_id,status,created_at DESC);
                CREATE TABLE IF NOT EXISTS manager_events (
                    id TEXT PRIMARY KEY, fund_id TEXT NOT NULL, event_date TEXT NOT NULL,
                    category TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL,
                    source TEXT NOT NULL, is_sample INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
                );
            """)

    def _seed_samples(self) -> None:
        with self._connect() as con:
            if con.execute("SELECT COUNT(*) FROM funds").fetchone()[0]:
                return
            funds, nav, holdings = load_samples()
            for item in funds.to_dict("records"):
                details = json_safe(item)
                con.execute(
                    "INSERT INTO funds VALUES (?,?,?,?,?,1)",
                    (str(item["fund_id"]), str(item["name"]), str(item["manager"]),
                     str(item["strategy"]), json.dumps(details, ensure_ascii=False)),
                )
            for row_number, item in enumerate(nav.to_dict("records"), 2):
                con.execute(
                    "INSERT INTO nav VALUES (?,?,?,?,?)",
                    (str(item["fund_id"]), _iso_date(item["date"]), float(item["nav"]),
                     "nav_monthly.csv（合成演示）", row_number),
                )
            for row_number, item in enumerate(holdings.to_dict("records"), 2):
                con.execute(
                    "INSERT INTO holdings(fund_id,asset,weight_pct,as_of,source_file,source_row) VALUES (?,?,?,?,?,?)",
                    (str(item["fund_id"]), str(item["asset"]), float(item["weight_pct"]),
                     _iso_date(item["as_of"]), "holdings.csv（合成演示）", row_number),
                )

    def _seed_optional_assets(self) -> None:
        """Add synthetic classroom reports/history once without replacing user data."""
        reports = SAMPLE_DIR / "manager_reports"
        if reports.exists():
            for path in sorted(reports.glob("*.txt")):
                fund_id = path.name.split("_")[0]
                if self.get_fund(fund_id) is None:
                    continue
                period = "current" if "2025Q4" in path.stem else "prior"
                self.add_document(fund_id, path.name, path.read_bytes(), period=period, is_sample=True)
        else:
            note = SAMPLE_DIR / "manager_note.txt"
            if note.exists():
                self.add_document("FOF-001", note.name, note.read_bytes(), period="current", is_sample=True)
        holdings_file = SAMPLE_DIR / "holdings_history.csv"
        if holdings_file.exists():
            frame = pd.read_csv(holdings_file, dtype={"fund_id": str})
            with self._connect() as con:
                for row_number, item in enumerate(frame.to_dict("records"), 2):
                    fund_id = str(item.get("fund_id", ""))
                    as_of = _iso_date(item.get("as_of"))
                    asset = str(item.get("asset", ""))
                    if not as_of or not fund_id or not asset or self.get_fund(fund_id) is None:
                        continue
                    present = con.execute(
                        "SELECT 1 FROM holdings WHERE fund_id=? AND as_of=? AND asset=?",
                        (fund_id, as_of, asset),
                    ).fetchone()
                    if not present:
                        con.execute(
                            "INSERT INTO holdings(fund_id,asset,weight_pct,as_of,source_file,source_row) VALUES (?,?,?,?,?,?)",
                            (fund_id, asset, float(item["weight_pct"]), as_of,
                             _clean_name(item.get("source_file") or holdings_file.name), row_number),
                        )
        events_file = SAMPLE_DIR / "manager_events.csv"
        if events_file.exists():
            frame = pd.read_csv(events_file, dtype={"fund_id": str}).fillna("")
            with self._connect() as con:
                for item in frame.to_dict("records"):
                    fund_id = str(item.get("fund_id", ""))
                    date = _iso_date(item.get("event_date") or item.get("date"))
                    if not date or self.get_fund(fund_id) is None:
                        continue
                    title = str(item.get("title", ""))
                    event_id = str(item.get("event_id") or hashlib.sha256(f"{fund_id}|{date}|{title}".encode()).hexdigest()[:16])
                    con.execute(
                        "INSERT OR IGNORE INTO manager_events VALUES (?,?,?,?,?,?,?,1)",
                        (event_id, fund_id, date, str(item.get("category", "研究事件")), title,
                         str(item.get("description") or item.get("detail") or ""),
                         str(item.get("source_file") or item.get("source") or events_file.name)),
                    )

    def get_fund(self, fund_id: str) -> dict[str, Any] | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM funds WHERE fund_id=?", (str(fund_id),)).fetchone()
        if not row:
            return None
        details = json.loads(row["details_json"])
        return {**details, "fund_id": row["fund_id"], "name": row["name"],
                "manager": row["manager"], "strategy": row["strategy"], "is_sample": bool(row["is_sample"])}

    def update_fund_details(self, fund_id: str, updates: dict[str, Any]) -> bool:
        """Merge additional profile fields into a fund's details without touching NAV."""
        with self._connect() as con:
            row = con.execute("SELECT details_json, manager FROM funds WHERE fund_id=?", (str(fund_id),)).fetchone()
            if not row:
                return False
            details = json.loads(row["details_json"])
            details.update(json_safe(updates))
            manager = str(updates.get("manager", row["manager"]))
            con.execute("UPDATE funds SET details_json=?, manager=? WHERE fund_id=?",
                        (json.dumps(details, ensure_ascii=False, allow_nan=False), manager, str(fund_id)))
        return True

    def list_funds(self) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM funds ORDER BY is_sample ASC, fund_id").fetchall()
        return [{**json.loads(row['details_json']), 'fund_id': row['fund_id'], 'name': row['name'],
                 'manager': row['manager'], 'strategy': row['strategy'], 'is_sample': bool(row['is_sample'])}
                for row in rows]

    def _read_frame(self, sql: str, params: Iterable[Any] = ()) -> pd.DataFrame:
        """用无 row_factory 的连接直接读出 DataFrame，避免逐行 dict 转换（大表下慢）。"""
        con = sqlite3.connect(self.path, timeout=15)
        try:
            return pd.read_sql_query(sql, con, params=tuple(params))
        finally:
            con.close()

    def nav_frame(self, fund_id: str | None = None) -> pd.DataFrame:
        if fund_id is None:
            frame = self._read_frame("SELECT fund_id,date,nav,source_file,source_row FROM nav ORDER BY fund_id,date")
        else:
            frame = self._read_frame("SELECT fund_id,date,nav,source_file,source_row FROM nav WHERE fund_id=? ORDER BY date", [str(fund_id)])
        if not frame.empty:
            frame["date"] = pd.to_datetime(frame["date"])
        return frame

    def holdings_frame(self, fund_id: str | None = None) -> pd.DataFrame:
        if fund_id is None:
            frame = self._read_frame("SELECT fund_id,asset,weight_pct,as_of,source_file,source_row FROM holdings ORDER BY fund_id,as_of,asset")
        else:
            frame = self._read_frame("SELECT fund_id,asset,weight_pct,as_of,source_file,source_row FROM holdings WHERE fund_id=? ORDER BY as_of,asset", [str(fund_id)])
        if not frame.empty:
            frame["as_of"] = pd.to_datetime(frame["as_of"])
        return frame

    def list_documents(self, fund_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT id,fund_id,period,name,added_at,chunks_json,is_sample,sha256 FROM documents"
        args: tuple[Any, ...] = ()
        if fund_id is not None:
            query += " WHERE fund_id=?"
            args = (str(fund_id),)
        query += " ORDER BY added_at DESC, name DESC"
        with self._connect() as con:
            rows = con.execute(query, args).fetchall()
        return [{"id": row["id"], "fund_id": row["fund_id"], "period": row["period"],
                 "name": row["name"], "added_at": row["added_at"], "sha256": row['sha256'],
                 "chunks_count": len(json.loads(row["chunks_json"])), "is_sample": bool(row["is_sample"])}
                for row in rows]

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "fund_id": row["fund_id"], "period": row["period"],
                "name": row["name"], "added_at": row["added_at"],
                "chunks": json.loads(row["chunks_json"]), "is_sample": bool(row["is_sample"])}

    def full_documents(self, fund_id: str | None = None) -> list[dict[str, Any]]:
        return [document for item in self.list_documents(fund_id)
                if (document := self.get_document(item["id"])) is not None]

    def search_documents(self, query: str, fund_id: str | None = None, limit: int = 12) -> list[dict[str, Any]]:
        documents = self.full_documents(fund_id)
        by_id = {document["id"]: document for document in documents}
        indexed = [{"name": document["id"], "chunks": document["chunks"]} for document in documents]
        hits = retrieve(query, indexed, limit=max(1, min(limit, 50)))
        return [{"document_id": hit["file"], "source": by_id[hit["file"]]["name"],
                 "fund_id": by_id[hit["file"]]["fund_id"], "period": by_id[hit["file"]]["period"],
                 "location": hit["location"], "text": hit["text"], "score": round(hit["score"], 4)}
                for hit in hits]

    def add_document(self, fund_id: str, name: str, raw: bytes, *, period: str = "current", is_sample: bool = False) -> dict[str, Any]:
        if self.get_fund(fund_id) is None:
            raise ValueError(f"基金 {fund_id} 不在工作区。")
        if period not in {"current", "prior", "reference"}:
            raise ValueError("period 只能为 current、prior 或 reference。")
        if len(raw) > 50 * 1024 * 1024:
            raise ValueError("文件不能超过 50 MB。")
        filename = _clean_name(name)
        digest = hashlib.sha256(raw).hexdigest()
        with self._connect() as con:
            old = con.execute(
                "SELECT id FROM documents WHERE fund_id=? AND sha256=? AND period=?",
                (str(fund_id), digest, period),
            ).fetchone()
        if old:
            return self.get_document(old["id"])  # type: ignore[return-value]
        chunks = extract_document(filename, raw)
        document_id = f"DOC-{uuid.uuid4().hex[:12].upper()}"
        with self._connect() as con:
            con.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                (document_id, str(fund_id), period, filename, digest, _now(),
                 json.dumps(chunks, ensure_ascii=False), int(is_sample)),
            )
        return self.get_document(document_id)  # type: ignore[return-value]

    def save_run(self, fund_id: str, result: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
        run_id = f"RUN-{uuid.uuid4().hex[:12].upper()}"
        created_at = _now()
        payload = json_safe({**result, "id": run_id, "created_at": created_at})
        with self._connect() as con:
            con.execute(
                "INSERT INTO runs VALUES (?,?,?,?,?)",
                (run_id, str(fund_id), created_at, json.dumps(payload, ensure_ascii=False, allow_nan=False),
                 json.dumps(json_safe(inputs), ensure_ascii=False, allow_nan=False)),
            )
            self._insert_run_tasks(con, run_id, str(fund_id), payload, created_at)
        return payload

    def _insert_run_tasks(self, con: sqlite3.Connection, run_id: str, fund_id: str,
                          result: dict[str, Any], created_at: str) -> None:
        candidates = [{"question": item.get("question", ""), "priority": item.get("priority", "中"),
                       "related_claim_ids": item.get("related_claim_ids", []), "category": "claim"}
                      for item in result.get("follow_up_questions", [])]
        candidates.extend({"question": item.get("next_request", ""),
                           "priority": "高" if item.get("coverage") == "missing" else "中",
                           "related_claim_ids": [], "category": item.get("id", "playbook")}
                          for item in result.get("playbook", []) if item.get("coverage") != "complete")
        for item in candidates:
            question = str(item["question"]).strip()
            if not question:
                continue
            question_key = hashlib.sha256("".join(question.split()).encode("utf-8")).hexdigest()
            task_id = "TASK-" + hashlib.sha256(f"{run_id}|{question_key}".encode()).hexdigest()[:12].upper()
            con.execute(
                """INSERT OR IGNORE INTO research_tasks
                   (id,run_id,fund_id,question_key,question,priority,status,category,
                    related_claim_ids_json,created_at,updated_at,resolution_note)
                   VALUES (?,?,?,?,?,?,'open',?,?,?,?,'')""",
                (task_id, run_id, fund_id, question_key, question, str(item["priority"]),
                 str(item["category"]), json.dumps(item["related_claim_ids"], ensure_ascii=False),
                 created_at, created_at),
            )

    def _backfill_run_tasks(self) -> None:
        with self._connect() as con:
            rows = con.execute("SELECT id,fund_id,created_at,result_json FROM runs").fetchall()
            for row in rows:
                self._insert_run_tasks(con, row["id"], row["fund_id"],
                                       json.loads(row["result_json"]), row["created_at"])

    def list_tasks(self, fund_id: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM research_tasks"
        conditions, args = [], []
        if fund_id:
            conditions.append("fund_id=?")
            args.append(str(fund_id))
        if run_id:
            conditions.append("run_id=?")
            args.append(str(run_id))
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, created_at DESC, id"
        with self._connect() as con:
            rows = con.execute(query, args).fetchall()
        return [{"id": row["id"], "run_id": row["run_id"], "fund_id": row["fund_id"],
                 "question": row["question"], "priority": row["priority"], "status": row["status"],
                 "category": row["category"], "related_claim_ids": json.loads(row["related_claim_ids_json"]),
                 "created_at": row["created_at"], "updated_at": row["updated_at"],
                 "resolution_note": row["resolution_note"]} for row in rows]

    def update_task(self, task_id: str, status: str, resolution_note: str | None = None) -> dict[str, Any] | None:
        if status not in {"open", "in_progress", "resolved"}:
            raise ValueError("任务状态必须为 open、in_progress 或 resolved。")
        with self._connect() as con:
            row = con.execute("SELECT run_id,resolution_note FROM research_tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                return None
            note = row["resolution_note"] if resolution_note is None else str(resolution_note).strip()
            con.execute("UPDATE research_tasks SET status=?,resolution_note=?,updated_at=? WHERE id=?",
                        (status, note, _now(), task_id))
            run_id = row["run_id"]
        return next((item for item in self.list_tasks(run_id=run_id) if item["id"] == task_id), None)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as con:
            row = con.execute("SELECT result_json FROM runs WHERE id=?", (run_id,)).fetchone()
        return json.loads(row["result_json"]) if row else None

    def list_runs(self, fund_id: str | None = None, limit: int = 60) -> list[dict[str, Any]]:
        query = "SELECT r.id,r.fund_id,r.created_at,r.result_json,f.name FROM runs r JOIN funds f ON r.fund_id=f.fund_id"
        args: list[Any] = []
        if fund_id:
            query += " WHERE r.fund_id=?"
            args.append(str(fund_id))
        query += " ORDER BY r.created_at DESC,r.rowid DESC LIMIT ?"
        args.append(int(limit))
        with self._connect() as con:
            rows = con.execute(query, args).fetchall()
        summaries = []
        for row in rows:
            result = json.loads(row["result_json"])
            claims = result.get("claims", [])
            summaries.append({
                "id": row["id"], "fund_id": row["fund_id"], "fund_name": row["name"],
                "created_at": row["created_at"], "claim_count": len(claims),
                "contradicted_count": sum(c.get("status") == "contradicted" for c in claims),
                "unverifiable_count": sum(c.get("status") in {"inconclusive", "unverifiable"} for c in claims),
                "evidence_count": len(result.get("evidence", [])),
                "is_demo": bool(result.get("is_demo")),
            })
        return summaries

    def list_events(self, fund_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM manager_events"
        args: tuple[Any, ...] = ()
        if fund_id:
            query += " WHERE fund_id=?"
            args = (str(fund_id),)
        query += " ORDER BY event_date DESC,id DESC"
        with self._connect() as con:
            rows = con.execute(query, args).fetchall()
        return [{**dict(row), "date": row["event_date"], "description": row["detail"],
                 "type": row["category"]} for row in rows]

    def save_market_fund(self, profile: dict[str, Any], nav: pd.DataFrame) -> int:
        """Commit a complete public-data snapshot atomically; never touch sample IDs."""
        fid = profile["fund_id"]
        if not fid.startswith("CN-") or nav.empty:
            raise ValueError("公开数据基金编号或净值为空。")
        rows = [(fid, str(row.date), float(row.nav), str(row.source_file), index + 2)
                for index, row in enumerate(nav.itertuples())]
        if any(not math.isfinite(row[2]) or row[2] <= 0 for row in rows):
            raise ValueError("来源存在非有限或非正净值。")
        with self._connect() as con:
            con.execute("INSERT INTO funds VALUES (?,?,?,?,?,0) ON CONFLICT(fund_id) DO UPDATE SET name=excluded.name, manager=excluded.manager, strategy=excluded.strategy, details_json=excluded.details_json, is_sample=0",
                        (fid, profile["name"], profile["manager"], profile["strategy"], json.dumps(profile, ensure_ascii=False, allow_nan=False)))
            con.execute("DELETE FROM nav WHERE fund_id=?", (fid,))
            con.executemany("INSERT INTO nav VALUES (?,?,?,?,?)", rows)
        return len(rows)

    def upsert_funds(self, records: Iterable[dict[str, Any]], *, source_file: str) -> int:
        count = 0
        with self._connect() as con:
            for item in records:
                fund_id = str(item.get("fund_id", "")).strip()
                name = str(item.get("name", "")).strip()
                manager = str(item.get("manager", "")).strip()
                strategy = str(item.get("strategy", "")).strip()
                if not all((fund_id, name, manager, strategy)):
                    raise ValueError("基金档案需要非空的 fund_id、name、manager、strategy。")
                details = {**json_safe(item), "source_file": _clean_name(source_file)}
                con.execute(
                    "INSERT INTO funds VALUES (?,?,?,?,?,0) ON CONFLICT(fund_id) DO UPDATE SET name=excluded.name, manager=excluded.manager, strategy=excluded.strategy, details_json=excluded.details_json, is_sample=0",
                    (fund_id, name, manager, strategy, json.dumps(details, ensure_ascii=False, allow_nan=False)),
                )
                count += 1
        return count

    def upsert_nav(self, records: Iterable[dict[str, Any]], *, source_file: str) -> int:
        rows = list(records)
        if not rows:
            raise ValueError("净值文件没有可导入的记录。")
        count = 0
        with self._connect() as con:
            for item in rows:
                fund_id = str(item.get("fund_id", "")).strip()
                date = _iso_date(item.get("date"))
                try:
                    value = float(item.get("nav"))
                except (TypeError, ValueError):
                    value = float("nan")
                if not fund_id or not date or not math.isfinite(value) or value <= 0:
                    raise ValueError("净值含无效基金编号、日期或非正数值；请修正后重试。")
                if not con.execute("SELECT 1 FROM funds WHERE fund_id=?", (fund_id,)).fetchone():
                    raise ValueError(f"基金 {fund_id} 不在工作区，请先导入基金档案。")
                con.execute(
                    "INSERT INTO nav VALUES (?,?,?,?,?) ON CONFLICT(fund_id,date) DO UPDATE SET nav=excluded.nav,source_file=excluded.source_file,source_row=excluded.source_row",
                    (fund_id, date, value, _clean_name(source_file), item.get("source_row")),
                )
                count += 1
        return count

    def upsert_holdings(self, records: Iterable[dict[str, Any]], *, source_file: str) -> int:
        rows = list(records)
        if not rows:
            raise ValueError("持仓文件没有可导入的记录。")
        normalized: list[tuple[str, str, float, str, str, Any]] = []
        for item in rows:
            fund_id = str(item.get("fund_id", "")).strip()
            asset = str(item.get("asset", "")).strip()
            as_of = _iso_date(item.get("as_of"))
            try:
                weight = float(item.get("weight_pct"))
            except (TypeError, ValueError):
                weight = float("nan")
            if not fund_id or not asset or not as_of or not math.isfinite(weight) or not 0 <= weight <= 100:
                raise ValueError("持仓含无效基金编号、资产类别、日期或百分数权重。")
            if self.get_fund(fund_id) is None:
                raise ValueError(f"基金 {fund_id} 不在工作区，请先导入基金档案。")
            normalized.append((fund_id, asset, weight, as_of, _clean_name(source_file), item.get("source_row")))
        with self._connect() as con:
            snapshots = {(row[0], row[3]) for row in normalized}
            for fund_id, as_of in snapshots:
                con.execute("DELETE FROM holdings WHERE fund_id=? AND as_of=?", (fund_id, as_of))
            con.executemany(
                "INSERT INTO holdings(fund_id,asset,weight_pct,as_of,source_file,source_row) VALUES (?,?,?,?,?,?)",
                normalized,
            )
        return len(normalized)

    def upsert_fof_holdings(self, records: Iterable[dict[str, Any]], *, source_file: str) -> int:
        """Replace one FOF's underlying-fund holdings for each (fund_id, report_date)."""
        rows = list(records)
        if not rows:
            raise ValueError("底层基金持仓没有可导入的记录。")
        normalized: list[tuple[str, str, str, float, str, str, Any]] = []
        for item in rows:
            fund_id = str(item.get("fund_id", "")).strip()
            target_code = str(item.get("target_code", "")).strip()
            target_name = str(item.get("target_name", "")).strip()
            report_date = _iso_date(item.get("report_date"))
            try:
                weight = float(item.get("weight_pct"))
            except (TypeError, ValueError):
                weight = float("nan")
            if not fund_id or not target_code or not report_date or not math.isfinite(weight) or not 0 <= weight <= 100:
                raise ValueError("底层基金持仓含无效基金编号、底层代码、报告期或百分数权重。")
            if self.get_fund(fund_id) is None:
                raise ValueError(f"基金 {fund_id} 不在工作区，请先导入基金档案。")
            normalized.append((fund_id, target_code, target_name, weight, report_date,
                               _clean_name(source_file), item.get("source_row")))
        with self._connect() as con:
            snapshots = {(row[0], row[4]) for row in normalized}
            for fund_id, report_date in snapshots:
                con.execute("DELETE FROM fof_holdings WHERE fund_id=? AND report_date=?", (fund_id, report_date))
            con.executemany(
                "INSERT INTO fof_holdings(fund_id,target_code,target_name,weight_pct,report_date,source_file,source_row) VALUES (?,?,?,?,?,?,?)",
                normalized,
            )
        return len(normalized)

    def fof_holdings_frame(self, fund_id: str | None = None) -> pd.DataFrame:
        if fund_id is None:
            frame = self._read_frame(
                "SELECT fund_id,target_code,target_name,weight_pct,report_date,source_file,source_row "
                "FROM fof_holdings ORDER BY fund_id,report_date,target_code")
        else:
            frame = self._read_frame(
                "SELECT fund_id,target_code,target_name,weight_pct,report_date,source_file,source_row "
                "FROM fof_holdings WHERE fund_id=? ORDER BY report_date,target_code", [str(fund_id)])
        if not frame.empty:
            frame["report_date"] = pd.to_datetime(frame["report_date"])
        return frame

    def _analytics_cache_path(self) -> Path:
        return self.path.parent / "analytics_cache.pkl"

    def _fingerprint(self, nav: pd.DataFrame, holdings: pd.DataFrame) -> str:
        # 轻量签名（行数 + 日期范围 + 数值和），替代逐单元格哈希。
        # 原 hash_pandas_object 对 90 万+ 净值点每请求哈希约 5s；导入新数据时该签名会自然变化。
        sig = []
        if not nav.empty:
            sig.append(f"nav:{len(nav)}:{nav['date'].min()}:{nav['date'].max()}:{round(float(nav['nav'].sum()), 6)}")
        else:
            sig.append("nav:0")
        if not holdings.empty:
            sig.append(f"hol:{len(holdings)}:{holdings['as_of'].min()}:{holdings['as_of'].max()}:{round(float(holdings['weight_pct'].sum()), 6)}")
        else:
            sig.append("hol:0")
        return hashlib.sha256(";".join(sig).encode("utf-8")).hexdigest()

    def _analytics_disk_load(self) -> dict[str, tuple[str, dict[str, Any], dict[str, Any]]]:
        if getattr(self, "_analytics_disk", None) is not None:
            return self._analytics_disk
        import pickle

        path = self._analytics_cache_path()
        disk: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
        if path.exists():
            try:
                with open(path, "rb") as fh:
                    loaded = pickle.load(fh)
                if isinstance(loaded, dict):
                    disk = loaded
            except Exception:
                disk = {}
        self._analytics_disk = disk
        self._analytics_dirty = False
        return disk

    def _analytics_disk_save(self) -> None:
        import pickle

        if not getattr(self, "_analytics_dirty", False):
            return
        path = self._analytics_cache_path()
        try:
            with open(path, "wb") as fh:
                pickle.dump(getattr(self, "_analytics_disk", {}), fh)
            self._analytics_dirty = False
        except Exception:
            pass

    def precompute_analytics(self) -> int:
        """一次性计算并持久化全部基金的 metrics+analytics，消除冷启动开销。"""
        from .data import fund_metrics
        from .research_tools import research_analytics

        all_nav = self.nav_frame()
        all_holdings = self.holdings_frame()
        nav_by = {fid: sub for fid, sub in all_nav.groupby("fund_id", sort=False)} if not all_nav.empty else {}
        hol_by = {fid: sub for fid, sub in all_holdings.groupby("fund_id", sort=False)} if not all_holdings.empty else {}
        empty_nav = all_nav.iloc[0:0]
        empty_hol = all_holdings.iloc[0:0]
        disk = self._analytics_disk_load()
        for fund in self.list_funds():
            fid = fund["fund_id"]
            nav = nav_by.get(fid, empty_nav)
            holdings = hol_by.get(fid, empty_hol)
            fingerprint = self._fingerprint(nav, holdings)
            hit = disk.get(fid)
            if hit is not None and hit[0] == fingerprint:
                continue
            analytics = research_analytics(nav, holdings, fid)
            for field in ("period_returns", "rolling_returns", "drawdown_path"):
                analytics["nav_diagnostics"].pop(field, None)
            disk[fid] = (fingerprint, json_safe(analytics), json_safe(fund_metrics(nav, fid)))
            self._analytics_dirty = True
        self._analytics_disk_save()
        return len(disk)

    def workspace(self) -> dict[str, Any]:
        from .research_tools import fund_correlations, research_analytics

        funds = []
        all_nav = self.nav_frame()
        all_holdings = self.holdings_frame()
        all_fof_holdings = self.fof_holdings_frame()
        # 预分组一次，避免对每只基金重复做 O(全表) 的布尔掩码过滤（原实现为 O(F×N)）。
        nav_by_fund = {fid: sub for fid, sub in all_nav.groupby("fund_id", sort=False)} if not all_nav.empty else {}
        holdings_by_fund = {fid: sub for fid, sub in all_holdings.groupby("fund_id", sort=False)} if not all_holdings.empty else {}
        fof_by_fund = {fid: sub for fid, sub in all_fof_holdings.groupby("fund_id", sort=False)} if not all_fof_holdings.empty else {}
        empty_nav = all_nav.iloc[0:0]
        empty_holdings = all_holdings.iloc[0:0]
        empty_fof = all_fof_holdings.iloc[0:0]
        # 事件与资料一次性读全表后在内存分组，避免对每只基金各开一次连接查询（1102×2 次约 12s）。
        events_by_fund: dict[str, list[dict[str, Any]]] = {}
        for ev in self.list_events():
            events_by_fund.setdefault(ev.get("fund_id", ""), []).append(ev)
        docs_by_fund: dict[str, list[dict[str, Any]]] = {}
        for doc in self.list_documents():
            docs_by_fund.setdefault(doc.get("fund_id", ""), []).append(doc)
        for fund in self.list_funds():
            fid = fund["fund_id"]
            nav = nav_by_fund.get(fid, empty_nav)
            holdings = holdings_by_fund.get(fid, empty_holdings)
            fof_holdings = fof_by_fund.get(fid, empty_fof)
            # 图表只需有限个点即可还原路径；把全量净值降采样到每只最多 120 个点，
            # 避免 workspace() 一次性序列化 90 万+ 个净值点（约 100MB）拖垮首屏。
            nav_pts = nav
            if len(nav_pts) > 120:
                nav_pts = nav_pts.iloc[:: max(1, len(nav_pts) // 120)]
            nav_points = [{"date": row.date.date().isoformat(), "nav": float(row.nav), "source_file": row.source_file}
                          for row in nav_pts.itertuples()]
            holding_points = [{"asset": row.asset, "weight_pct": float(row.weight_pct),
                               "as_of": row.as_of.date().isoformat(), "source_file": row.source_file}
                              for row in holdings.itertuples()]
            fof_points = [{"target_code": row.target_code, "target_name": row.target_name,
                           "weight_pct": float(row.weight_pct),
                           "report_date": row.report_date.date().isoformat(), "source_file": row.source_file}
                          for row in fof_holdings.itertuples()]
            fingerprint = self._fingerprint(nav, holdings)
            cached = self._analytics_cache.get(fid)
            if cached is None or cached[0] != fingerprint:
                disk = self._analytics_disk_load()
                cached = disk.get(fid)
                if cached is None or cached[0] != fingerprint:
                    analytics = research_analytics(nav, holdings, fid)
                    for field in ('period_returns', 'rolling_returns', 'drawdown_path'):
                        analytics['nav_diagnostics'].pop(field, None)
                    cached = (fingerprint, json_safe(analytics), json_safe(fund_metrics(nav, fid)))
                    disk[fid] = cached
                    self._analytics_dirty = True
                self._analytics_cache[fid] = cached
            latest_snapshot = max((row["as_of"] for row in holding_points), default=None)
            funds.append({**fund, "metrics": cached[2],
                          "nav": nav_points, "holdings": [row for row in holding_points if row["as_of"] == latest_snapshot],
                          "holdings_history": holding_points, "fof_holdings": fof_points,
                          "analytics": cached[1],
                          "events": events_by_fund.get(fid, []), "reports": docs_by_fund.get(fid, []),
                          "latest_snapshot": latest_snapshot})
        runs = self.list_runs()
        tasks = self.list_tasks()
        manager_groups: dict[str, dict[str, Any]] = {}
        for fund in funds:
            manager = fund["manager"]
            item = manager_groups.setdefault(manager, {"id": hashlib.sha256(manager.encode()).hexdigest()[:10],
                                                       "name": manager, "fund_ids": [], "fund_count": 0})
            item["fund_ids"].append(fund["fund_id"])
            item["fund_count"] += 1
        return json_safe({
            "funds": funds, "managers": list(manager_groups.values()),
            "documents": self.list_documents(), "runs": runs,
            "latest_run": self.get_run(runs[0]["id"]) if runs else None,
            "events": self.list_events(), "tasks": tasks,
            "correlations": fund_correlations(all_nav.loc[all_nav["fund_id"].isin([f["fund_id"] for f in funds if not f["is_sample"]][:8] or [f["fund_id"] for f in funds][:8])], pd.DataFrame(funds)),
            "dashboard": {"fund_count": len(funds), "manager_count": len(manager_groups),
                          "document_count": len(self.list_documents()), "run_count": len(runs),
                          "claim_count": sum(run["claim_count"] for run in runs),
                          "open_task_count": sum(task["status"] != "resolved" for task in tasks)},
            "demo_mode": all(fund["is_sample"] for fund in funds),
        })
