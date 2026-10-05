import contextlib
import os
import sqlite3
from pathlib import Path


class BusyError(RuntimeError):
    pass


@contextlib.contextmanager
def lock(cfg):
    cfg.ensure_dirs()
    path = cfg.paths["state"] / "pipeline.lock"
    stream = open(path, "a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise BusyError("다른 파이프라인 작업이 실행 중입니다.") from error
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise BusyError("다른 파이프라인 작업이 실행 중입니다.") from error
        acquired = True
        yield
    finally:
        if acquired:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


class Store:
    def __init__(self, cfg):
        cfg.ensure_dirs()
        self.path = cfg.paths["state"] / "jobs.sqlite3"
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout = 30000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, source_hash TEXT NOT NULL,
            config_hash TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT,
            result_path TEXT, note_path TEXT, error TEXT, ai_status TEXT)""")
        self.db.commit()

    def close(self):
        self.db.close()

    def get(self, job_id):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def begin(self, job_id, source, source_hash, config_hash, timestamp):
        self.db.execute("""INSERT INTO jobs(id,source,source_hash,config_hash,status,attempts,created_at,updated_at)
            VALUES(?,?,?,?, 'processing',1,?,?)
            ON CONFLICT(id) DO UPDATE SET status='processing',attempts=jobs.attempts+1,updated_at=excluded.updated_at,error=NULL""", (job_id, source, source_hash, config_hash, timestamp, timestamp))
        self.db.commit()

    def finish(self, job_id, timestamp, result, note, ai_status):
        self.db.execute("UPDATE jobs SET status='completed',updated_at=?,completed_at=?,result_path=?,note_path=?,error=NULL,ai_status=? WHERE id=?", (timestamp, timestamp, str(result), str(note), ai_status, job_id))
        self.db.commit()

    def fail(self, job_id, timestamp, message):
        self.db.execute("UPDATE jobs SET status='failed',updated_at=?,error=? WHERE id=?", (timestamp, message[:2000], job_id))
        self.db.commit()

    def reset_failed(self):
        self.db.execute("UPDATE jobs SET attempts=0 WHERE status IN ('failed','processing')")
        self.db.commit()

    def recent(self, limit=100):
        return [dict(row) for row in self.db.execute("SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,))]

    def completed(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM jobs WHERE status='completed' ORDER BY completed_at")]
