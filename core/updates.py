"""Release notifications. No executable downloads or automatic installation."""
import asyncio
import json
from pathlib import Path
import re
import time
import threading

import httpx
import keyring

from .version import VERSION

REPOSITORY = "WildLIK/WileyAI"
API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
PAGE = f"https://github.com/{REPOSITORY}/releases"
KEY_SERVICE = "WileyAI.GitHub"


def version(value):
    match = re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\+[A-Za-z0-9.-]+)?", value)
    return tuple(map(int, match.groups())) if match else None


class Updates:
    def __init__(self, root, *, client=None):
        self.path = Path(root) / "updates.json"
        self.lock = asyncio.Lock()
        self.guard = threading.RLock()
        self.client = client
        self.running = False
        self.value = {"automatic": True, "checked_at": None, "available": None,
                      "dismissed": "", "notified": "", "error": "", "etag": "", "etag_version": ""}
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.value.update({key: saved[key] for key in self.value if key in saved})
        except (OSError, ValueError, TypeError):
            pass
        if self.value["etag_version"] != VERSION:
            # A cached 304 was computed against another installed version; ask GitHub for the full release again.
            self.value["etag"] = ""
        self.forget_installed()

    def forget_installed(self):
        """Drops an offer that is not newer than the running version (e.g. after upgrading)."""
        item = self.value.get("available")
        parsed = version(item.get("version", "")) if isinstance(item, dict) else None
        if item is not None and not (parsed and parsed > version(VERSION)):
            self.value["available"] = None

    def save(self):
        with self.guard:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".part")
            temporary.write_text(json.dumps(self.value, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)

    def state(self):
        try:
            has_key = bool(keyring.get_password(KEY_SERVICE, REPOSITORY))
        except Exception:
            has_key = False
        return {**self.value, "current_version": VERSION, "checking": self.running,
                "has_key": has_key, "page": PAGE}

    def configure(self, automatic, token=None):
        if token is not None:
            try:
                if token:
                    keyring.set_password(KEY_SERVICE, REPOSITORY, token)
                else:
                    try:
                        keyring.delete_password(KEY_SERVICE, REPOSITORY)
                    except keyring.errors.PasswordDeleteError:
                        pass
            except Exception as error:
                raise ValueError("Не удалось сохранить ключ GitHub в Windows") from error
            self.value["etag"] = ""
        self.value["automatic"] = automatic
        self.save()
        return self.state()

    async def check(self):
        async with self.lock:
            self.running = True
            try:
                headers = {"Accept": "application/vnd.github+json", "User-Agent": f"WileyAI/{VERSION}",
                           "X-GitHub-Api-Version": "2022-11-28"}
                try:
                    token = keyring.get_password(KEY_SERVICE, REPOSITORY)
                except Exception:
                    token = None
                if token:
                    headers["Authorization"] = "Bearer " + token
                if self.value.get("etag"):
                    headers["If-None-Match"] = self.value["etag"]
                async with httpx.AsyncClient(transport=self.client, timeout=15, follow_redirects=False) as client:
                    async with client.stream("GET", API, headers=headers) as response:
                        if response.status_code == 304:
                            pass
                        elif response.status_code == 404:
                            raise ValueError("Выпуск не найден или репозиторий закрыт. Для закрытого проекта сохраните ключ GitHub с доступом к WileyAI; первый выпуск также должен быть опубликован.")
                        elif response.status_code in {401, 403}:
                            raise ValueError("GitHub ограничил запрос или не принял ключ. Проверьте доступ и повторите позже.")
                        else:
                            response.raise_for_status()
                            data = bytearray()
                            async for block in response.aiter_bytes():
                                data.extend(block)
                                if len(data) > 512 * 1024:
                                    raise ValueError("Ответ GitHub слишком большой")
                            release = json.loads(data)
                            tag = release.get("tag_name", "")
                            parsed = version(tag)
                            if not parsed or release.get("draft") or release.get("prerelease"):
                                raise ValueError("Выпуск GitHub не содержит стабильной версии")
                            self.value["available"] = ({"version": tag, "url": PAGE + "/tag/" + tag}
                                                       if parsed > version(VERSION) else None)
                            self.value["etag"] = response.headers.get("etag", "")
                            self.value["etag_version"] = VERSION
                self.value["error"] = ""
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.value["error"] = (str(error) if isinstance(error, ValueError)
                                       else "Не удалось проверить GitHub. Проверьте подключение к интернету.")
            finally:
                self.running = False
                self.value["checked_at"] = time.time()
                self.forget_installed()
                self.save()
            return self.state()

    def dismiss(self):
        self.value["dismissed"] = (self.value.get("available") or {}).get("version", "")
        self.save()
        return self.state()

    def claim(self):
        with self.guard:
            item = self.value.get("available")
            if not self.value["automatic"] or not item or item["version"] in {
                self.value["notified"], self.value["dismissed"]
            }:
                return None
            self.value["notified"] = item["version"]
            self.save()
            return item

    async def run(self):
        await asyncio.sleep(15)
        while True:
            try:
                if self.value["automatic"] and time.time() - (self.value["checked_at"] or 0) >= 6 * 3600:
                    await self.check()
            except Exception:
                # A failed save must not stop future background checks.
                pass
            await asyncio.sleep(60)
