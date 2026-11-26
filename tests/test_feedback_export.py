import io
import json
import time
from zipfile import ZipFile

from core.feedback import archive, entries
from core.config import Settings
from core.updates import Updates


def test_zip_contains_only_reviewed_technical_fields_and_description(tmp_path):
    updates = Updates(tmp_path)
    updates.record("check_failed")
    settings = Settings(stt_model="gigaam-v3", stt_quality="balanced", tts_engine="sapi",
                        model="qwen3.5:4b", fast_model="SYNTHETIC_PRIVATE_MODEL",
                        base_url="https://example.invalid/SYNTHETIC_SECRET",
                        personality="SYNTHETIC_PERSONAL_MEMORY")
    fault_file = tmp_path / "process-faults.json"
    fault_file.write_text(json.dumps([{"at": int(time.time()), "component": "gpu", "reason": "crashed",
                                       "code": 2, "details": "SYNTHETIC_RAW_LOG"}]), encoding="utf-8")
    report = entries(settings, {**updates.state(), "error": "SYNTHETIC_TOKEN_IN_ERROR"}, "Нейтральный тест", fault_file)
    with ZipFile(io.BytesIO(archive(report))) as zipped:
        assert set(zipped.namelist()) == {"system.json", "diagnostics.json", "description.txt"}
        for name in zipped.namelist():
            assert zipped.read(name).decode("utf-8") == report[name]
        assert all("SYNTHETIC_" not in zipped.read(name).decode("utf-8") for name in zipped.namelist())
        assert json.loads(zipped.read("diagnostics.json"))["update_events"][0][1] == "check_failed"
        assert json.loads(zipped.read("diagnostics.json"))["process_faults"][0]["code"] == 2
        system = json.loads(zipped.read("system.json"))
        assert system["build_id"] and "git_commit" in system and "git_dirty" in system
        assert system["engines"]["llm"]["model"] == "qwen3.5:4b"
        assert system["engines"]["llm"]["fast_model"].startswith("custom-")
        assert system["engines"]["stt"]["model"] == "gigaam-v3"
        assert system["engines"]["tts"]["engine"] == "sapi"


def test_technical_history_bounded_and_pruned(tmp_path):
    updates = Updates(tmp_path)
    now = int(time.time())
    updates.value["history"] = [[now, "checked"]] * 110
    assert len(updates.history()) == 100
    updates.value["history"].extend([[now - 2 * 86400, "downloaded"], [now, "RAW_HISTORY_NOT_ALLOWED"]])
    updates.value["retention_days"] = 1
    updates.record("checked")
    assert len(updates.history()) <= 100
    assert {code for _, code in Updates(tmp_path).history()} == {"checked"}
