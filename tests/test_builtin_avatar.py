from core.config import Settings


def test_packaged_default_is_portable_and_preserves_user_selection(monkeypatch):
    monkeypatch.setenv("WILEYAI_PACKAGED", "1")
    assert Settings().avatar_path == "builtin:fairy"
    assert Settings(avatar_path="").avatar_path == ""
    assert Settings(avatar_path="D:/my-avatar.vrm").avatar_path == "D:/my-avatar.vrm"
    monkeypatch.delenv("WILEYAI_PACKAGED")
    assert Settings().avatar_path == ""
