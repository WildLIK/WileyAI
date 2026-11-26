import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(script):
    spec = importlib.util.spec_from_file_location(script, ROOT / "scripts" / f"{script}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_only_requires_explicit_opt_in_and_never_accepts_a_bad_signature(tmp_path, monkeypatch):
    release = load("prepare-update-release")
    installer = tmp_path / "WileyAI-Setup-0.14.44-x64.exe"
    installer.write_bytes(b"fixture installer")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    monkeypatch.setattr(release, "run", lambda *args, **kwargs: '{"version":"0.14.44","status":"NotSigned"}')
    with pytest.raises(ValueError, match="Authenticode"):
        release.windows(installer, "0.14.44")
    item = release.windows(installer, "0.14.44", allow_unsigned=True)
    assert item["authentication"] == "signed-manifest"
    monkeypatch.setattr(release, "run", lambda *args, **kwargs: '{"version":"0.14.44","status":"HashMismatch"}')
    with pytest.raises(ValueError, match="Authenticode"):
        release.windows(installer, "0.14.44", allow_unsigned=True)


def test_production_bundle_rejects_local_experimental_models(tmp_path):
    import zipfile

    audit = load("audit-release-assets")
    apk = tmp_path / "test.apk"
    with zipfile.ZipFile(apk, "w") as archive:
        archive.writestr("assets/wake-stage1/C_v2.onnx", b"test-only")
    with pytest.raises(ValueError, match="wake-stage1"):
        audit.android_assets(apk)


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows DPAPI vault")
def test_encrypted_vault_backup_and_restore_preserve_both_signers(tmp_path, monkeypatch):
    vault = load("release-vault")
    first, first_vault = vault.locations(tmp_path / "first.keystore")
    second, second_vault = vault.locations(tmp_path / "second.keystore")
    monkeypatch.setattr(vault.getpass, "getpass", lambda _: "synthetic-recovery-passphrase")
    vault.initialize(first, first_vault)
    with pytest.raises(FileExistsError):
        vault.initialize(first, first_vault)
    archive = tmp_path / "safe.wileybackup"
    vault.backup(first, first_vault, archive)
    assert b"PRIVATE KEY" not in archive.read_bytes()
    vault.restore(second, second_vault, archive)
    assert first.read_bytes() == second.read_bytes()
    assert (first_vault / "manifest.spki").read_bytes() == (second_vault / "manifest.spki").read_bytes()
    with pytest.raises(FileExistsError):
        vault.restore(second, second_vault, archive)
