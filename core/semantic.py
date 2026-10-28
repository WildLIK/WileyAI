"""Optional local embeddings. Cache contains vectors/hashes, never source text.

Every retrieval starts from the current scoped SQLite records, so stale cache
entries cannot resurrect removed text or cross chat/project boundaries.
"""
import asyncio
import hashlib
import json
import math
import sqlite3
import struct
from contextlib import contextmanager, closing
from pathlib import Path

import httpx

from .document_library import Library
from .document_summary import chunks
from .storage import SOURCE_TEXT

try:
    import numpy
except ImportError:  # Optional in the base runtime; scoring falls back to Python.
    numpy = None

MAX_CHUNKS = 10000
MAX_CACHE = 12000
MODEL = "embeddinggemma:300m"


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vector(value):
    if not isinstance(value, list) or not 2 <= len(value) <= 4096:
        raise ValueError("Некорректная размерность embeddings")
    if any(type(n) not in {int, float} or not math.isfinite(n) for n in value):
        raise ValueError("Некорректный вектор embeddings")
    size = math.sqrt(sum(n * n for n in value))
    if not math.isfinite(size) or size < 1e-12:
        raise ValueError("Пустой вектор embeddings")
    return [n / size for n in value]


def scores(values, query):
    """Cosine similarity with a unit query. Stored float32 vectors are re-normalized."""
    if not values:
        return []
    if numpy is None:
        result = []
        for value in values:
            value = vector([float(n) for n in value])
            if len(value) != len(query):
                raise ValueError("Размерность изменилась")
            result.append(sum(a * b for a, b in zip(value, query)))
        return result
    matrix = numpy.asarray(values, dtype=numpy.float64)
    if matrix.ndim != 2 or matrix.shape[1] != len(query):
        raise ValueError("Размерность изменилась")
    norms = numpy.linalg.norm(matrix, axis=1)
    if not numpy.isfinite(norms).all() or (norms < 1e-12).any():
        raise ValueError("Некорректный вектор embeddings")
    return ((matrix @ numpy.asarray(query, dtype=numpy.float64)) / norms).tolist()


def configuration(settings):
    return digest(settings.embedding_base_url + "\n" + settings.embedding_model + "\nchunk-1200-v1")


class SemanticIndex:
    def __init__(self, store):
        self.store = store
        self.path = Path(store.root) / "semantic.db"
        self.task = None
        self.job = {"state": "idle", "completed": 0, "total": 0, "text": "Индекс ещё не создан"}
        self.lock = asyncio.Lock()
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS vectors (model TEXT NOT NULL, hash TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(model,hash))")
            db.execute("CREATE TABLE IF NOT EXISTS meta (config TEXT PRIMARY KEY, model TEXT NOT NULL)")

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            yield db

    def sources(self, scoped, kind="all", ids=None):
        rows = []
        # `ids` narrows the read to known records (the post-query recheck).
        only, chosen = ("", ()) if ids is None else (" AND {}.id IN (SELECT value FROM json_each(?))", (json.dumps(sorted(ids)),))
        # Read source records in one consistent transaction, including scope.
        with scoped.db() as db:
            db.execute("BEGIN")
            library = Library(scoped)
            library.check_chat(db)
            if kind in {"all", "memory"}:
                for row in db.execute(f"SELECT m.*,{SOURCE_TEXT} FROM memories m WHERE m.scope_id=?" + only.format("m") + " ORDER BY m.id", (scoped.scope_id, *chosen)):
                    item = dict(row)
                    rows.append({"kind": "memory", "id": item["id"], "offset": 0, "text": item["content"], "item": item})
            if kind in {"all", "document"}:
                where, args = library.visible()
                for row in db.execute("SELECT d.* FROM document_library d WHERE " + where + only.format("d") + " ORDER BY d.id", (*args, *chosen)):
                    item = dict(row)
                    for offset, text in chunks(item["content"], 1200):
                        rows.append({"kind": "document", "id": item["id"], "offset": offset, "text": text,
                                     "item": {key: value for key, value in item.items() if key != "content"}, "total": len(item["content"])})
                        if len(rows) > MAX_CHUNKS:
                            raise ValueError("В пространстве больше 10 000 фрагментов. Используется обычный поиск")
        for row in rows:
            # Document names are part of matching but never commands.
            row["input"] = ((row["item"].get("name", "") + "\n") if row["kind"] == "document" else "") + row["text"]
            row["hash"] = digest(row["input"])
        if len(rows) > MAX_CHUNKS:
            raise ValueError("В пространстве больше 10 000 фрагментов. Используется обычный поиск")
        return rows

    async def model_key(self, settings):
        async with httpx.AsyncClient(base_url=settings.embedding_base_url, timeout=10, trust_env=False) as http:
            response = await http.get("/api/tags")
            response.raise_for_status()
            data = response.json()
        rows = data.get("models", [])
        if not isinstance(rows, list):
            raise ValueError("Движок не вернул список embeddings-моделей")
        name = settings.embedding_model
        matched = next((row for row in rows if row.get("name") in {name, name + ":latest"}), None)
        if not matched or not isinstance(matched.get("digest"), str) or not matched["digest"]:
            raise ValueError("Embeddings-модель не установлена. Откройте «Модели → Семантический поиск»")
        return configuration(settings) + ":" + digest(matched["digest"])

    async def embed(self, settings, texts):
        async with httpx.AsyncClient(base_url=settings.embedding_base_url, timeout=60, trust_env=False) as http:
            # Do not silently truncate a chunk the index claims to represent.
            async with http.stream("POST", "/api/embed", json={"model": settings.embedding_model,
                    "input": texts, "truncate": False, "keep_alive": "1m"}) as response:
                response.raise_for_status()
                body = bytearray()
                async for part in response.aiter_bytes(chunk_size=32768):
                    body.extend(part)
                    if len(body) > 2 * 1024 * 1024:
                        raise ValueError("Слишком большой ответ embeddings")
        rows = json.loads(body).get("embeddings")
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise ValueError("Движок не вернул все embeddings")
        values = [vector(row) for row in rows]
        if len({len(row) for row in values}) != 1:
            raise ValueError("Embeddings имеют разную размерность")
        return values

    def cached(self, key, hashes=None):
        with self.db() as db:
            result = {}
            if hashes is None:
                records = db.execute("SELECT hash,value FROM vectors WHERE model=?", (key,)).fetchall()
            else:
                chosen = list(set(hashes))
                records = []
                for offset in range(0, len(chosen), 500):
                    batch = chosen[offset:offset + 500]
                    records.extend(db.execute("SELECT hash,value FROM vectors WHERE model=? AND hash IN (" + ",".join("?" for _ in batch) + ")", (key, *batch)).fetchall())
            for fingerprint, raw in records:
                if isinstance(raw, bytes) and len(raw) % 4 == 0 and 8 <= len(raw) <= 16384:
                    result[fingerprint] = numpy.frombuffer(raw, "<f4") if numpy is not None else list(struct.unpack("<" + "f" * (len(raw) // 4), raw))
                elif isinstance(raw, str):
                    result[fingerprint] = json.loads(raw)  # Early local development cache.
            return result

    def status(self, scoped):
        settings = self.store.settings()
        rows = self.sources(scoped)
        with self.db() as db:
            row = db.execute("SELECT model FROM meta WHERE config=?", (configuration(settings),)).fetchone()
        cached = self.cached(row[0], [item["hash"] for item in rows]) if row else {}
        ready = sum(row["hash"] in cached for row in rows)
        return {"enabled": settings.embedding_enabled, "model": settings.embedding_model, "ready": ready,
                "total": len(rows), "complete": ready == len(rows), "job": self.job}

    def start(self, scoped):
        if not self.store.settings().embedding_enabled:
            raise ValueError("Сначала включите семантический поиск")
        if self.task and not self.task.done():
            raise ValueError("Индекс уже строится. Дождитесь окончания или остановите его")
        self.job = {"state": "running", "completed": 0, "total": 0, "text": "Проверяю локальную модель…"}
        self.task = asyncio.create_task(self.rebuild(scoped))

    def reserve(self, settings, key, rows, pending):
        with self.db() as db:
            # A model switch (including updated weights under the same
            # tag) cannot mix dimensions or results from the old model.
            db.execute("DELETE FROM vectors WHERE model!=?", (key,))
            db.execute("DELETE FROM meta")
            db.execute("INSERT INTO meta VALUES (?,?)", (configuration(settings), key))
            # Reserve room for this entire scope before writing. Keep
            # current hashes; evict older scopes from the derived cache.
            db.execute("CREATE TEMP TABLE keep_hash (hash TEXT PRIMARY KEY)")
            db.executemany("INSERT OR IGNORE INTO keep_hash VALUES (?)", [(row["hash"],) for row in rows])
            count = db.execute("SELECT count(*) FROM vectors").fetchone()[0]
            excess = max(0, count + pending - MAX_CACHE)
            if excess:
                db.execute("DELETE FROM vectors WHERE rowid IN (SELECT rowid FROM vectors v WHERE NOT EXISTS (SELECT 1 FROM keep_hash k WHERE k.hash=v.hash) ORDER BY rowid LIMIT ?)", (excess,))

    def write(self, key, batch, values):
        with self.db() as db:
            db.executemany("INSERT OR REPLACE INTO vectors VALUES (?,?,?)", [(key, row[0], struct.pack("<" + "f" * len(value), *value)) for row, value in zip(batch, values)])

    async def rebuild(self, scoped):
        try:
            async with self.lock:
                settings = await asyncio.to_thread(self.store.settings)
                key = await self.model_key(settings)
                rows = await asyncio.to_thread(self.sources, scoped)
                cached = await asyncio.to_thread(self.cached, key, [row["hash"] for row in rows])
                unique = {row["hash"]: row["input"] for row in rows if row["hash"] not in cached}
                pending = list(unique.items())
                self.job.update(total=len(pending), text="Создаю локальный индекс…")
                await asyncio.to_thread(self.reserve, settings, key, rows, len(pending))
                for offset in range(0, len(pending), 8):
                    current = await asyncio.to_thread(self.store.settings)
                    if not current.embedding_enabled or configuration(current) != configuration(settings):
                        raise ValueError("Настройки embeddings изменились. Повторите построение индекса")
                    batch = pending[offset:offset + 8]
                    values = await self.embed(settings, [row[1] for row in batch])
                    if cached and any(len(v) != len(next(iter(cached.values()))) for v in values):
                        raise ValueError("Размерность модели изменилась. Очистите и перестройте индекс")
                    await asyncio.to_thread(self.write, key, batch, values)
                    cached.update({row[0]: value for row, value in zip(batch, values)})
                    self.job.update(completed=min(offset + 8, len(pending)))
                self.job.update(state="done", text="Индекс построен. Изменённые документы и память потребуют обновления")
        except asyncio.CancelledError:
            self.job.update(state="cancelled", text="Построение остановлено. Доступен обычный поиск")
        except Exception:
            self.job.update(state="error", text="Не удалось построить индекс. Проверьте локальный Ollama и embeddings-модель; обычный поиск доступен")

    async def search(self, scoped, query, kind, limit=20, ids=None):
        settings = await asyncio.to_thread(self.store.settings)
        if not settings.embedding_enabled or not query.strip():
            return None, ""
        try:
            key = await self.model_key(settings)

            def snapshot():
                rows = self.sources(scoped, kind, ids)
                return rows, self.cached(key, [row["hash"] for row in rows])

            rows, cached = await asyncio.to_thread(snapshot)
            if any(row["hash"] not in cached for row in rows):
                return None, "Индекс требует обновления; показаны совпадения обычного поиска"
            query_vector, = await self.embed(settings, [query[:1000]])

            def rank():
                similarity = scores([cached[row["hash"]] for row in rows], query_vector)
                ranked = [row | {"score": round(score, 5)} for row, score in zip(rows, similarity) if score >= .35]
                # Recheck scope/content after network awaits. No deleted or edited
                # source is ever taken from the cache or an old in-flight snapshot.
                fresh = {(row["kind"], row["id"], row["offset"]): row["hash"] for row in self.sources(scoped, kind, {row["id"] for row in ranked})} if ranked else {}
                return [row for row in ranked if fresh.get((row["kind"], row["id"], row["offset"])) == row["hash"]], self.store.settings()

            ranked, current = await asyncio.to_thread(rank)
            if configuration(current) != configuration(settings) or not current.embedding_enabled:
                return None, "Настройки поиска изменились; показан обычный поиск"
            ranked.sort(key=lambda row: row["score"], reverse=True)
            return ranked[:limit], ""
        except asyncio.CancelledError:
            raise
        except Exception:
            return None, "Семантическая модель недоступна; показаны совпадения обычного поиска"

    async def close(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
