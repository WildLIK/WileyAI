"""Tenant-bound AEAD storage. SQLite contains encrypted records/events and hashed client tokens."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .protocol import GatewayError


def private_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        path.chmod(0o700)


def new_id():
    return uuid.uuid4().hex


class Store:
    def __init__(self, directory: Path, key: bytes):
        if len(key) != 32:
            raise ValueError("Gateway master key must contain exactly 32 bytes")
        self.root = directory.resolve()
        private_directory(self.root)
        self.cipher = AESGCM(key)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / "gateway.db", check_same_thread=False, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS records(owner TEXT NOT NULL,id TEXT NOT NULL,kind TEXT NOT NULL,payload BLOB NOT NULL,updated REAL NOT NULL,PRIMARY KEY(owner,id));
          CREATE INDEX IF NOT EXISTS records_kind ON records(owner,kind,updated);
          CREATE TABLE IF NOT EXISTS tokens(digest TEXT PRIMARY KEY,owner TEXT NOT NULL,role TEXT NOT NULL,label TEXT NOT NULL,created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS events(owner TEXT NOT NULL,run_id TEXT NOT NULL,seq INTEGER NOT NULL,payload BLOB NOT NULL,PRIMARY KEY(owner,run_id,seq));
          CREATE TABLE IF NOT EXISTS requests(owner TEXT NOT NULL,request_id TEXT NOT NULL,digest TEXT NOT NULL,run_id TEXT NOT NULL,PRIMARY KEY(owner,request_id));
        """)
        self.db.commit()
        if os.name != "nt":
            (self.root / "gateway.db").chmod(0o600)

    def seal(self, owner, identifier, value):
        nonce = secrets.token_bytes(12)
        return nonce + self.cipher.encrypt(nonce, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(), f"{owner}:{identifier}".encode())

    def open(self, owner, identifier, blob):
        try:
            return json.loads(self.cipher.decrypt(blob[:12], blob[12:], f"{owner}:{identifier}".encode()))
        except Exception:
            raise GatewayError("storage_unavailable", "Не удалось открыть защищённые данные Gateway.", 503) from None

    def put(self, owner, identifier, kind, value):
        with self.lock, self.db:
            self.db.execute("INSERT INTO records VALUES(?,?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET kind=excluded.kind,payload=excluded.payload,updated=excluded.updated",
                            (owner, identifier, kind, self.seal(owner, identifier, value), time.time()))

    def get(self, owner, identifier, kind=None):
        with self.lock:
            row = self.db.execute("SELECT kind,payload FROM records WHERE owner=? AND id=?", (owner, identifier)).fetchone()
        if row is None or (kind and row[0] != kind):
            raise GatewayError("not_found", "Объект не найден или принадлежит другому подключению.", 404)
        return self.open(owner, identifier, row[1])

    def list(self, owner, kind):
        with self.lock:
            rows = self.db.execute("SELECT id,payload FROM records WHERE owner=? AND kind=? ORDER BY updated DESC", (owner, kind)).fetchall()
        return [(identifier, self.open(owner, identifier, blob)) for identifier, blob in rows]

    def owners(self):
        with self.lock:
            return [r[0] for r in self.db.execute("SELECT DISTINCT owner FROM tokens").fetchall()]

    def delete(self, owner, identifier):
        with self.lock, self.db:
            self.db.execute("DELETE FROM records WHERE owner=? AND id=?", (owner, identifier))
            self.db.execute("DELETE FROM events WHERE owner=? AND run_id=?", (owner, identifier))

    def token(self, owner, role="client", label="Android"):
        value = secrets.token_urlsafe(40)
        with self.lock, self.db:
            self.db.execute("INSERT INTO tokens VALUES(?,?,?,?,?)", (hashlib.sha256(value.encode()).hexdigest(), owner, role, label, time.time()))
        return value

    def authenticate(self, value):
        if not isinstance(value, str) or not 20 <= len(value) <= 150:
            raise GatewayError("unauthorized", "Нужен токен WileyAI Gateway.", 401)
        with self.lock:
            row = self.db.execute("SELECT owner,role FROM tokens WHERE digest=?", (hashlib.sha256(value.encode()).hexdigest(),)).fetchone()
        if row is None:
            raise GatewayError("unauthorized", "Токен Gateway отклонён или отозван.", 401)
        return row

    def revoke(self, owner, value):
        with self.lock, self.db:
            self.db.execute("DELETE FROM tokens WHERE owner=? AND digest=?", (owner, hashlib.sha256(value.encode()).hexdigest()))

    def reserve(self, owner, request_id, digest, run_id, run):
        with self.lock, self.db:
            row = self.db.execute("SELECT digest,run_id FROM requests WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
            if row:
                if row[0] == "cancelled":
                    raise GatewayError("request_cancelled", "Этот запрос уже отменён и не будет отправлен провайдеру.", 409)
                if row[0] != digest:
                    raise GatewayError("idempotency_conflict", "Этот идентификатор запроса уже использован с другим содержимым.", 409)
                return row[1], False
            self.db.execute("INSERT INTO requests VALUES(?,?,?,?)", (owner, request_id, digest, run_id))
            self.db.execute("INSERT INTO records VALUES(?,?,?,?,?)", (owner, run_id, "run", self.seal(owner, run_id, run), time.time()))
            return run_id, True

    def delete_request(self, owner, request_id, run_id):
        with self.lock, self.db:
            self.db.execute("DELETE FROM requests WHERE owner=? AND request_id=? AND run_id=?", (owner, request_id, run_id))
            self.db.execute("DELETE FROM records WHERE owner=? AND id=?", (owner, run_id))

    def cancel_request(self, owner, request_id):
        with self.lock, self.db:
            row = self.db.execute("SELECT run_id FROM requests WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
            if row:
                return row[0]
            self.db.execute("INSERT INTO requests VALUES(?,?,?,?)", (owner, request_id, "cancelled", ""))
            return ""

    def event(self, owner, run_id, event):
        with self.lock, self.db:
            seq = self.db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE owner=? AND run_id=?", (owner, run_id)).fetchone()[0]
            self.db.execute("INSERT INTO events VALUES(?,?,?,?)", (owner, run_id, seq, self.seal(owner, f"{run_id}:{seq}", event)))
            return seq

    def events(self, owner, run_id, after=0):
        with self.lock:
            rows = self.db.execute("SELECT seq,payload FROM events WHERE owner=? AND run_id=? AND seq>? ORDER BY seq LIMIT 100", (owner, run_id, after)).fetchall()
        return [(seq, self.open(owner, f"{run_id}:{seq}", blob)) for seq, blob in rows]

    def close(self):
        self.db.close()
