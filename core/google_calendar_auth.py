"""Desktop Google OAuth: PKCE, one-use loopback callback, OS credential storage.

No credentials are put in Settings, SQLite, logs or backup archives. The client
is supplied by the user; this source tree intentionally contains no OAuth keys.
"""
import asyncio
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import keyring

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = {"https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar.calendarlist.readonly"}


class GoogleError(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__("Событие Google изменилось. Обновите предпросмотр" if status == 412 else
                         "Google отклонил доступ. Подключите аккаунт заново" if status == 401 else
                         f"Google отклонил запрос (HTTP {status}). Повторите проверку подключения")


async def response_json(client, method, url, max_bytes=2*1024*1024, **kwargs):
    """Bound response size and never expose a provider's raw error body."""
    try:
        async with client.stream(method, url, **kwargs) as response:
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ValueError("Google вернул слишком большой ответ")
            if response.status_code not in (200, 201, 204):
                raise GoogleError(response.status_code)
            result = json.loads(data) if data else {}
            if not isinstance(result, dict):
                raise ValueError("Некорректный ответ Google")
            return result
    except (httpx.HTTPError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("Нет надёжного ответа Google. Проверьте интернет и повторите предпросмотр; результат отправки мог сохраниться") from error


class GoogleAuth:
    def __init__(self, root, client=None, *, scopes=None, service="WileyAI.GoogleCalendar", permission_text="списку календарей и событиям"):
        self.key = hashlib.sha256(str(root.resolve()).casefold().encode()).hexdigest()
        self.scopes = frozenset(SCOPES if scopes is None else scopes)
        self.service = service
        self.permission_text = permission_text
        self.client = client
        self.lock = asyncio.Lock()
        self.pending = None
        self.error = ""

    def read(self):
        try:
            value = keyring.get_password(self.service, self.key)
            return json.loads(value) if value else {}
        except Exception as error:
            raise ValueError("Не удалось прочитать подключение Google из системного хранилища") from error

    def write(self, value):
        try:
            keyring.set_password(self.service, self.key, json.dumps(value))
        except Exception as error:
            raise ValueError("Не удалось сохранить подключение Google в системном хранилище") from error

    def status(self):
        value = self.read()
        return {"configured": bool(value.get("client")), "connected": bool(value.get("refresh_token") or value.get("access_token")),
                "pending": self.pending is not None, "error": self.error}

    async def configure(self, document):
        async with self.lock:
            if len(document.encode()) > 16384:
                raise ValueError("JSON OAuth-клиента превышает 16 КБ")
            try:
                value = json.loads(document)["installed"]
                client_id, client_secret = value["client_id"], value.get("client_secret", "")
                if not isinstance(client_id, str) or not 20 < len(client_id) < 300 or not client_id.endswith(".apps.googleusercontent.com"):
                    raise ValueError()
                if not isinstance(client_secret, str) or len(client_secret) > 500:
                    raise ValueError()
                if value.get("auth_uri") != "https://accounts.google.com/o/oauth2/auth" or value.get("token_uri") != TOKEN_URL:
                    raise ValueError()
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError("Нужен JSON OAuth-клиента Google типа Desktop app (installed)") from error
            await self.cancel()
            self.write({"client": {"client_id": client_id, "client_secret": client_secret}, "epoch": secrets.token_hex(16)})
            self.error = ""
            return self.status()

    async def request(self, method, url, **kwargs):
        if self.client is not None:
            return await response_json(self.client, method, url, **kwargs)
        async with httpx.AsyncClient(timeout=25, trust_env=False, follow_redirects=False) as client:
            return await response_json(client, method, url, **kwargs)

    async def start(self, scopes=None):
        async with self.lock:
            value = self.read()
            if not value.get("client"):
                raise ValueError("Сначала загрузите JSON клиента Google Desktop app")
            await self.cancel()
            verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            attempt = {"state": state, "verifier": verifier, "path": "/oauth/" + secrets.token_hex(16), "client": value["client"], "scopes": frozenset(self.scopes if scopes is None else scopes)}
            server = await asyncio.start_server(lambda reader, writer: self.callback(attempt, reader, writer), "127.0.0.1", 0, limit=8192)
            port = server.sockets[0].getsockname()[1]
            attempt.update(server=server, redirect=f"http://127.0.0.1:{port}" + attempt["path"], host=f"127.0.0.1:{port}")
            self.pending = attempt
            attempt["timeout"] = asyncio.create_task(self.expire(attempt))
            self.error = ""
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            return {"url": AUTH_URL + "?" + urlencode({**{key: value["client"][key] for key in ("client_id",)},
                    "redirect_uri": attempt["redirect"], "response_type": "code", "scope": " ".join(sorted(attempt["scopes"])),
                    "state": state, "code_challenge": challenge, "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"})}

    async def expire(self, attempt):
        await asyncio.sleep(300)
        async with self.lock:
            if self.pending is attempt:
                self.error = "Время входа истекло. Нажмите «Войти через Google» ещё раз"
                await self.cancel()

    async def cancel(self):
        attempt, self.pending = self.pending, None
        if attempt:
            attempt["server"].close()
            # Do not wait here: Python 3.12 also waits for the callback's own
            # connection, which is closed only after the token exchange below.
            task = attempt.get("timeout")
            if task and task is not asyncio.current_task():
                task.cancel()

    async def callback(self, attempt, reader, writer):
        ok = False
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            lines = raw.decode("ascii").split("\r\n")
            method, target, protocol = lines[0].split(" ")
            headers = [line.split(":", 1) for line in lines[1:] if ":" in line]
            hosts = [value.strip() for key, value in headers if key.lower() == "host"]
            parsed = urlsplit(target)
            args = parse_qs(parsed.query, max_num_fields=8, keep_blank_values=True)
            if method != "GET" or protocol != "HTTP/1.1" or hosts != [attempt["host"]] or parsed.path != attempt["path"] or parsed.netloc or parsed.scheme:
                raise ValueError()
            if any(len(values) != 1 for values in args.values()) or not secrets.compare_digest(args.get("state", [""])[0], attempt["state"]):
                raise ValueError()
            async with self.lock:
                if self.pending is not attempt:
                    raise ValueError()
                await self.cancel()  # Consume state even if token exchange fails.
                if "error" in args:
                    self.error = "Вход Google отменён или доступ не предоставлен"
                else:
                    code = args.get("code", [""])[0]
                    if not code or len(code) > 4096:
                        raise ValueError()
                    tokens = await self.request("POST", TOKEN_URL, data={**attempt["client"], "code": code, "code_verifier": attempt["verifier"],
                                                "redirect_uri": attempt["redirect"], "grant_type": "authorization_code"})
                    self.validate_tokens(tokens, require_scope=True, required_scopes=attempt["scopes"])
                    if not tokens.get("refresh_token"):
                        raise ValueError("Google не выдал доступ для повторного подключения. Отзовите старое разрешение WileyAI и войдите заново")
                    self.write({"client": attempt["client"], "epoch": secrets.token_hex(16), **self.token_values(tokens)})
                    self.error = ""
                    ok = True
        except (Exception, asyncio.CancelledError) as error:
            if self.pending is None and isinstance(error, ValueError) and str(error):
                self.error = str(error)
        finally:
            message = "Google connected. You can close this tab and return to WileyAI." if ok else "Connection was not completed. Return to WileyAI to see the status."
            data = ("<!doctype html><meta charset=utf-8><title>WileyAI</title><p>" + message + "</p>").encode()
            writer.write(f"HTTP/1.1 {200 if ok else 400} OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(data)}\r\nCache-Control: no-store\r\nContent-Security-Policy: default-src 'none'\r\nConnection: close\r\n\r\n".encode() + data)
            try:
                await writer.drain()
            except (ConnectionError, OSError):
                pass
            writer.close()
            await writer.wait_closed()

    def validate_tokens(self, tokens, require_scope=False, required_scopes=None):
        if not isinstance(tokens.get("access_token"), str) or not 1 <= len(tokens["access_token"]) <= 16384 or not isinstance(tokens.get("token_type"), str) or tokens["token_type"].lower() != "bearer":
            raise ValueError("Google не выдал корректный токен доступа")
        if require_scope and (not isinstance(tokens.get("scope"), str) or not (self.scopes if required_scopes is None else required_scopes) <= set(tokens["scope"].split())):
            raise ValueError("Разрешите все запрошенные права Google, затем повторите вход" if required_scopes is not None and required_scopes != self.scopes else "Разрешите доступ к " + self.permission_text + ", затем повторите вход")
        if tokens.get("refresh_token") is not None and (not isinstance(tokens["refresh_token"], str) or not 1 <= len(tokens["refresh_token"]) <= 16384):
            raise ValueError("Некорректное разрешение повторного входа Google")
        if type(tokens.get("expires_in")) is not int or not 1 <= tokens["expires_in"] <= 86400:
            raise ValueError("Некорректный срок доступа Google")

    @staticmethod
    def token_values(tokens):
        return {"access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token"), "expires_at": time.time() + tokens["expires_in"],
                **({"granted_scopes": tokens["scope"].split()} if isinstance(tokens.get("scope"), str) else {})}

    async def access(self):
        async with self.lock:
            value = self.read()
            if value.get("access_token") and value.get("expires_at", 0) > time.time() + 60:
                return value["access_token"], value["epoch"]
            if not value.get("refresh_token"):
                raise ValueError("Подключите аккаунт Google в календаре")
            tokens = await self.request("POST", TOKEN_URL, data={**value["client"], "refresh_token": value["refresh_token"], "grant_type": "refresh_token"})
            self.validate_tokens(tokens)
            updated = self.token_values(tokens)
            updated["refresh_token"] = updated["refresh_token"] or value["refresh_token"]
            self.write({**value, **updated})
            return updated["access_token"], value["epoch"]

    async def disconnect(self):
        async with self.lock:
            await self.cancel()
            value = self.read()
            self.write({"client": value.get("client"), "epoch": secrets.token_hex(16)})
            self.error = ""
            return self.status()

    async def close(self):
        async with self.lock:
            await self.cancel()
