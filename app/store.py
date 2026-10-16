"""Persistencia en SQLite. PRIMARY KEY (comando.id)."""
import os
import sqlite3
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Bogota")


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, evento TEXT, modulo INTEGER,"
            " ts_ms INTEGER, fecha TEXT, hora TEXT)"
        )
        self._db.execute("CREATE INDEX IF NOT EXISTS ix_fecha ON events(fecha, modulo)")
        self._lock = threading.Lock()
        self.version = 0  # sube con cada inserción nueva; lo usa el stream SSE

    def insert_many(self, rows):
        data = []
        for r in rows:
            dt = datetime.fromtimestamp(r["ts_ms"] / 1000, TZ)  # epoch UTC -> hora Colombia
            data.append((r["id"], r["evento"], r["modulo"], r["ts_ms"],
                         dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M:%S")))
        with self._lock:
            before = self._db.total_changes
            self._db.executemany("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)", data)
            self._db.commit()
            new = self._db.total_changes - before
            if new:
                self.version += 1
        return new, len(data) - new

    @staticmethod
    def _where(fecha, eventos, modulo=None):
        cond, args = [], []
        if fecha:
            cond.append("fecha=?"); args.append(fecha)
        if eventos:
            cond.append(f"evento IN ({','.join('?' * len(eventos))})"); args += list(eventos)
        if modulo is not None:
            cond.append("modulo=?"); args.append(modulo)
        return (" WHERE " + " AND ".join(cond)) if cond else "", args

    def counts(self, fecha, eventos):
        w, a = self._where(fecha, eventos)
        with self._lock:
            cur = self._db.execute(f"SELECT modulo, COUNT(*) FROM events{w} GROUP BY modulo ORDER BY modulo", a)
            return dict(cur.fetchall())

    def rows(self, fecha, eventos, modulo=None):
        w, a = self._where(fecha, eventos, modulo)
        with self._lock:
            cur = self._db.execute(f"SELECT fecha, hora, modulo, evento FROM events{w} ORDER BY ts_ms, id", a)
            return cur.fetchall()
