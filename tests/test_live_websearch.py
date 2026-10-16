"""Optional local-model test with a controlled local search service, no paid calls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
from unittest.mock import patch

from fastapi.testclient import TestClient
import pytest

from core.api import create_app


@pytest.mark.skipif(os.environ.get("WILEYAI_LIVE_TESTS") != "1", reason="Requires local Ollama qwen3.5:4b")
def test_real_model_answers_with_numbered_search_source(tmp_path):
    class Search(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"results": [{"title": "Контрольная публикация", "url": "https://example.com/wileyai", "content": "Контрольный код выпуска проекта WileyAI: КЕДР-84. Дата выпуска ещё не назначена."}]}, ensure_ascii=False).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Search)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    token = "live-search-test-0123456789abcdef"
    try:
        with patch("core.providers.get_key", return_value=""):
            with TestClient(create_app(tmp_path, token), headers={"Authorization": "Bearer " + token}) as api:
                settings = api.get("/settings").json()
                settings.update(search_enabled=True, search_base_url=f"http://127.0.0.1:{server.server_port}", temperature=0)
                assert api.put("/settings", json=settings).status_code == 200
                response = api.post("/chat", json={"text": "Найди в интернете контрольный код выпуска WileyAI. Ответь кратко с номером источника."})
                events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
                assert not any(item["type"] == "error" for item in events), events
                answer = next(item["message"] for item in events if item["type"] == "done")
                assert "КЕДР-84" in answer["content"] and "[1]" in answer["content"], answer
                assert answer["web_search"]["results"][0]["url"] == "https://example.com/wileyai"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
