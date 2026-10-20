"""Durable scheduled snapshots while the application is running."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import re
import threading
import uuid

from .backups import Backups

NAME = re.compile(r"^auto-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}\.wileyai\.json$")


class Background:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        with store.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS background_state (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)")

    def state(self):
        with self.store.db() as db:
            row = db.execute("SELECT value FROM background_state WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}

    def status(self):
        state = self.state()
        return {"last_backup": state.get("last_backup"), "path": state.get("path"), "error": state.get("error", ""),
                "directory": str(self.store.root / "backups" / "scheduled")}

    def tick(self, moment=None):
        if not self.lock.acquire(blocking=False):
            return
        try:
            moment = moment or datetime.now(timezone.utc)
            settings = self.store.settings()
            if settings.backup_schedule == "off":
                return
            local = moment.astimezone(ZoneInfo(settings.background_timezone))
            hour, minute = map(int, settings.backup_time.split(":"))
            due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if settings.backup_schedule == "weekly":
                due -= timedelta(days=(local.weekday() - settings.backup_weekday) % 7)
            if local < due:
                return
            slot = due.strftime("%Y-%m-%d")
            state = self.state()
            # A clock change or DST fold cannot repeat the same local date.
            if state.get("slot", "") >= slot or state.get("retry_after", "") > moment.isoformat():
                return
            try:
                content = Backups(self.store).export()  # Includes restore validation.
                folder = self.store.root / "backups" / "scheduled"
                folder.mkdir(parents=True, exist_ok=True)
                if folder.is_symlink() or folder.is_junction() or folder.parent.is_symlink() or folder.parent.is_junction():
                    raise ValueError("Каталог копий перенаправлен")
                name = "auto-" + moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8] + ".wileyai.json"
                target = folder / name
                temporary = folder / (name + ".tmp")
                try:
                    with temporary.open("xb") as file:
                        file.write(content)
                        file.flush()
                        os.fsync(file.fileno())
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
                state = {"slot": slot, "last_backup": moment.isoformat(), "path": str(target), "error": ""}
                # Only our own complete files inside the fixed directory are
                # eligible for retention; manual/recovery copies are untouched.
                candidates = sorted((path for path in folder.iterdir() if NAME.fullmatch(path.name)
                        and path.is_file() and not path.is_symlink() and not path.is_junction()), key=lambda path: path.name, reverse=True)
                for path in candidates[settings.backup_keep:]:
                    if path.resolve().parent == folder.resolve():
                        try:
                            path.unlink()
                        except OSError:
                            state["error"] = "Копия сохранена, но часть старых автоматических копий не удалось удалить"
            except Exception:
                state.update(error="Не удалось создать автоматическую копию. Проверьте свободное место и каталог копий", retry_after=(moment + timedelta(minutes=5)).isoformat())
            with self.store.db() as db:
                db.execute("INSERT OR REPLACE INTO background_state VALUES (1,?)", (json.dumps(state),))
        finally:
            self.lock.release()
