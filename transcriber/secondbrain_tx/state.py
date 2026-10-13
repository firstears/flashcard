from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    sha256 TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    note_path TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL,
    updated REAL NOT NULL
)
"""


def file_sha256(path: Path, block: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(block)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


class State:
    """작업 목록을 디스크(SQLite)에 저장한다. 프로그램이 꺼져도 이어서 처리한다."""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row
        self.db.execute(_SCHEMA)
        # 비정상 종료로 남은 '처리 중' 작업을 대기 상태로 되돌린다.
        self.db.execute("UPDATE jobs SET status=? WHERE status=?", (QUEUED, RUNNING))
        self.db.commit()

    def get(self, sha: str):
        return self.db.execute("SELECT * FROM jobs WHERE sha256=?", (sha,)).fetchone()

    def add(self, sha: str, path: Path) -> bool:
        """새 작업이면 True. 이미 같은 내용의 파일이 있으면 False."""
        if self.get(sha) is not None:
            return False
        now = time.time()
        self.db.execute(
            "INSERT INTO jobs(sha256,path,status,created,updated) VALUES(?,?,?,?,?)",
            (sha, str(path), QUEUED, now, now),
        )
        self.db.commit()
        return True

    def next_queued(self, max_attempts: int):
        return self.db.execute(
            "SELECT * FROM jobs WHERE status=? AND attempts<? ORDER BY created LIMIT 1",
            (QUEUED, max_attempts),
        ).fetchone()

    def start(self, sha: str) -> None:
        self.db.execute(
            "UPDATE jobs SET status=?, attempts=attempts+1, updated=? WHERE sha256=?",
            (RUNNING, time.time(), sha),
        )
        self.db.commit()

    def finish(self, sha: str, note_path: str) -> None:
        self.db.execute(
            "UPDATE jobs SET status=?, note_path=?, error='', updated=? WHERE sha256=?",
            (DONE, note_path, time.time(), sha),
        )
        self.db.commit()

    def fail(self, sha: str, error: str, max_attempts: int) -> None:
        row = self.get(sha)
        status = FAILED if row and row["attempts"] >= max_attempts else QUEUED
        self.db.execute(
            "UPDATE jobs SET status=?, error=?, updated=? WHERE sha256=?",
            (status, error[:500], time.time(), sha),
        )
        self.db.commit()

    def update_path(self, sha: str, path: Path) -> None:
        self.db.execute("UPDATE jobs SET path=? WHERE sha256=?", (str(path), sha))
        self.db.commit()

    def retry_failed(self) -> int:
        cur = self.db.execute(
            "UPDATE jobs SET status=?, attempts=0, error='' WHERE status=?", (QUEUED, FAILED)
        )
        self.db.commit()
        return cur.rowcount

    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    def recent(self, limit: int = 10):
        return self.db.execute(
            "SELECT * FROM jobs ORDER BY updated DESC LIMIT ?", (limit,)
        ).fetchall()

    def close(self) -> None:
        self.db.close()
