from concurrent.futures import ThreadPoolExecutor
import json
from fastapi.testclient import TestClient
import pytest
from core.api import create_app
from core.backups import Backups
from core.config import Settings
from core.storage import Store

TOKEN = "appearance-tests-token-0123456789"


@pytest.mark.parametrize("theme", ["aurora", "ice", "ember", "nebula"])
def test_visual_patch_preserves_model_voice_and_other_settings(tmp_path, theme):
    store = Store(tmp_path)
    store.save_settings(Settings(name="Моя Уайли", model="my-model", tts_voice="my-voice"))
    with TestClient(create_app(tmp_path, TOKEN), headers={"Authorization":"Bearer " + TOKEN}) as api:
        assert api.patch("/settings/appearance",json={"ui_theme":theme,"ui_glass":False}).status_code == 200
        config = api.get("/settings").json()
        assert config["model"] == "my-model" and config["tts_voice"] == "my-voice"
        assert config["name"] == "Моя Уайли" and config["ui_glass"] is False
    assert Store(tmp_path).settings().ui_theme == theme


@pytest.mark.parametrize("body", [{"ui_theme":"unknown"},{"ui_motion":"blink"},{"model":"other"},{"ui_theme":"ice","api_key":"never-store-this"}])
def test_invalid_visual_patch_does_not_change_settings(tmp_path, body):
    with TestClient(create_app(tmp_path,TOKEN),headers={"Authorization":"Bearer " + TOKEN}) as api:
        assert api.patch("/settings/appearance",json=body).status_code == 422
        assert api.get("/settings").json()["ui_theme"] == "aurora"


def test_visual_preferences_export_and_device_local_restore_policy(tmp_path):
    source = Store(tmp_path / "source")
    source.patch_settings({"ui_theme":"nebula","ui_motion":"reduced","ui_glass":False})
    archive = Backups(source).export()
    assert json.loads(archive)["settings"]["ui_theme"] == "nebula"
    target = Store(tmp_path / "target")
    target.patch_settings({"ui_theme":"ice"})
    manager = Backups(target)
    manager.restore(manager.preview(archive)["ticket"])
    assert target.settings().ui_theme == "ice"
    manager.restore(manager.preview(archive)["ticket"], connections=True)
    assert target.settings().ui_theme == "nebula" and target.settings().ui_motion == "reduced"


def test_concurrent_small_patches_do_not_replace_each_other(tmp_path):
    Store(tmp_path)
    with ThreadPoolExecutor(3) as pool:
        list(pool.map(lambda change: Store(tmp_path).patch_settings(change), [{"ui_theme":"ember"},{"ui_glass":False},{"ui_motion":"reduced"}]))
    config = Store(tmp_path).settings()
    assert config.ui_theme == "ember" and config.ui_motion == "reduced" and config.ui_glass is False
