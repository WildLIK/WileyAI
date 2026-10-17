import asyncio
import json

import httpx
import pytest

from core import updates


@pytest.fixture(autouse=True)
def isolated_keys(monkeypatch):
    keys = {}
    monkeypatch.setattr(updates.keyring, "get_password", lambda service, account: keys.get((service, account)))
    monkeypatch.setattr(updates.keyring, "set_password", lambda service, account, value: keys.__setitem__((service, account), value))
    monkeypatch.setattr(updates.keyring, "delete_password", lambda service, account: keys.pop((service, account), None))


def test_versions():
    assert updates.version("v0.2.10") > updates.version("0.2.9")
    for value in ("v0.3", "v0.3.0-beta", "v03.0.0", "https://example.com", "../../3.0.0"):
        assert updates.version(value) is None


def test_release_notification_is_once_persistent_and_can_be_dismissed(tmp_path):
    def handler(request):
        assert str(request.url) == updates.API
        return httpx.Response(200, headers={"ETag": '"one"'}, json={"tag_name": "v0.3.0", "html_url": "https://evil.invalid", "draft": False})
    checker = updates.Updates(tmp_path, client=httpx.MockTransport(handler))
    state = asyncio.run(checker.check())
    assert state["available"] == {"version": "v0.3.0", "url": updates.PAGE + "/tag/v0.3.0"}
    assert checker.claim()["version"] == "v0.3.0"
    assert checker.claim() is None
    next_checker = updates.Updates(tmp_path)
    assert next_checker.claim() is None
    next_checker.dismiss()
    assert next_checker.state()["dismissed"] == "v0.3.0"


def test_conditional_request_and_no_downgrade(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, headers={"ETag": "cached"}, json={"tag_name": updates.VERSION})
        assert request.headers["If-None-Match"] == "cached"
        return httpx.Response(304)
    checker = updates.Updates(tmp_path, client=httpx.MockTransport(handler))
    assert asyncio.run(checker.check())["available"] is None
    assert asyncio.run(checker.check())["error"] == ""


def test_private_repo_error_is_not_reported_as_up_to_date(tmp_path):
    checker = updates.Updates(tmp_path, client=httpx.MockTransport(lambda request: httpx.Response(404)))
    state = asyncio.run(checker.check())
    assert state["error"] and not state["available"]
    checker.configure(False, "github_pat_test")
    assert checker.state()["has_key"]
    assert "github_pat_test" not in checker.path.read_text(encoding="utf-8")
    assert "token" not in checker.state()
    assert checker.claim() is None
    checker.configure(True, "")
    assert not checker.state()["has_key"]


def test_auth_only_sent_to_fixed_api_and_not_returned(tmp_path):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer github_pat_example"
        assert request.url.host == "api.github.com"
        return httpx.Response(200, json={"tag_name": "v99.0.0"})
    checker = updates.Updates(tmp_path, client=httpx.MockTransport(handler))
    checker.configure(True, "github_pat_example")
    assert "github_pat_example" not in json.dumps(asyncio.run(checker.check()))


def test_failed_or_unstable_check_preserves_existing_offer(tmp_path):
    checker = updates.Updates(tmp_path, client=httpx.MockTransport(lambda request: httpx.Response(200, json={"tag_name": "v9.0.0-beta", "prerelease": True})))
    checker.value["available"] = {"version": "v1.0.0", "url": updates.PAGE}
    assert asyncio.run(checker.check())["available"]["version"] == "v1.0.0"
    assert checker.state()["error"]
