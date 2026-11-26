"""Prepare signed update metadata locally. Does not upload anything."""
import argparse
import base64
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.signed_updates import MANIFEST, MAX_ARTIFACT, NAME, version


def run(*args, env=None):
    return subprocess.run(args, env=env, stdout=subprocess.PIPE, encoding="utf-8", errors="replace",
                          check=True).stdout.strip()


def artifact(path, version_name, target, arch):
    if not NAME.fullmatch(path.name) or not 0 < path.stat().st_size <= MAX_ARTIFACT:
        raise ValueError("Invalid artifact filename or size")
    with path.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    return dict(platform=target, arch=arch, name=path.name, size=path.stat().st_size,
                sha256=digest, version=version_name)


def windows(path, version_name, *, allow_unsigned=False):
    declared = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    from core.version import VERSION
    if version_name != declared or version_name != VERSION:
        raise ValueError("Tag, package.json and core/version.py must agree")
    if path.name != f"WileyAI-Setup-{version_name}-x64.exe":
        raise ValueError("The installer filename must identify the release")
    env = {key: value for key, value in os.environ.items() if key.lower() != "psmodulepath"}
    env["WILEY_PUBLICATION_INSTALLER"] = str(path.resolve())
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    metadata = json.loads(run(str(executable), "-NoProfile", "-NonInteractive", "-Command",
                              "$ErrorActionPreference='Stop'; "
                              "$p=$env:WILEY_PUBLICATION_INSTALLER; "
                              "@{version=(Get-Item -LiteralPath $p).VersionInfo.ProductVersion; "
                              "status=(Get-AuthenticodeSignature -LiteralPath $p).Status.ToString()} | ConvertTo-Json -Compress", env=env))
    if metadata["version"] != version_name:
        raise ValueError("The installer's embedded ProductVersion does not match the release")
    status = metadata["status"]
    if status != "Valid" and (status != "NotSigned" or not allow_unsigned):
        raise ValueError("Windows installer requires a valid Authenticode signature")
    return {**artifact(path, version_name, "windows", "x64"),
            "authentication": "authenticode-and-signed-manifest" if status == "Valid" else "signed-manifest"}


def android(path, version_name, tools, prior_code, expected_signer):
    badging = run(str(tools / "aapt2.exe"), "dump", "badging", str(path))
    info = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging, re.M)
    arches = re.search(r"^native-code:(.*)$", badging, re.M)
    app_id = "ru.wildlik.wileyai.mobile"
    if (not info or info.group(1) != app_id or info.group(3) != version_name
            or int(info.group(2)) <= prior_code or not arches
            or not {"arm64-v8a", "x86_64"}.issubset(re.findall(r"'([^']+)'", arches.group(1)))):
        raise ValueError("APK identity, build counter, version or universal ABI mismatch")
    if "application-debuggable" in badging:
        raise ValueError("A debug APK cannot be published")
    result = run(str(tools / "apksigner.bat"), "verify", "--print-certs", str(path))
    signers = re.findall(r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-f]+)$", result, re.M)
    if len(signers) != 1 or signers[0] != expected_signer or re.search(r"certificate DN:.*\bdebug\b", result, re.I):
        raise ValueError("APK does not use the expected permanent release signer")
    run(sys.executable, str(ROOT / "scripts/check-android-16kb.py"), str(path))
    return {**artifact(path, version_name, "android", "universal"), "package_id": app_id,
            "version_code": int(info.group(2)), "signer_sha256": signers[0]}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--tag", required=True)
    cli.add_argument("--previous-version", required=True)
    cli.add_argument("--notes", type=Path, required=True)
    cli.add_argument("--key", type=Path, default=os.environ.get("WILEYAI_MANIFEST_KEY"))
    cli.add_argument("--ask-key-password", action="store_true")
    cli.add_argument("--windows", type=Path, required=True)
    cli.add_argument("--android", type=Path, required=True)
    cli.add_argument("--android-tools", type=Path, required=True)
    cli.add_argument("--previous-android-code", type=int, required=True)
    cli.add_argument("--android-signer", default=os.environ.get("WILEYAI_ANDROID_RELEASE_SIGNER"))
    cli.add_argument("--allow-unsigned-windows", action="store_true",
                     help="Allow a NotSigned installer verified by the trusted release manifest")
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()

    release = json.loads((ROOT / "release-version.json").read_text(encoding="utf-8"))
    if args.tag != "v" + release["version"] or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", args.tag):
        cli.error("Pass the release-version.json version as vMAJOR.MINOR.PATCH")
    if version(args.tag) <= version(args.previous_version):
        cli.error("The public version must increase")
    if (args.previous_android_code < 0 or release["androidVersionCode"] <= args.previous_android_code
            or not re.fullmatch(r"[0-9a-f]{64}", args.android_signer or "")):
        cli.error("Android requires an increasing versionCode and the permanent certificate digest")
    notes = args.notes.read_text(encoding="utf-8-sig").strip()
    if not 0 < len(notes) <= 8000:
        cli.error("Release notes must have 1–8000 characters")
    if args.key is None:
        cli.error("A signing-vault key or --key is required")
    configured_password = os.environ.get("WILEYAI_MANIFEST_PASSWORD")
    password = (getpass.getpass("Manifest key password: ").encode() if args.ask_key_password
                else configured_password.encode() if configured_password else None)
    key = serialization.load_pem_private_key(args.key.read_bytes(), password=password)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        cli.error("Manifest signer must be a P-256 key")
    actual = base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    if actual != os.environ.get("WILEYAI_UPDATE_PUBLIC_KEY"):
        cli.error("Manifest signer does not match the build's WILEYAI_UPDATE_PUBLIC_KEY")
    name = args.tag[1:]
    apk = android(args.android, name, args.android_tools, args.previous_android_code, args.android_signer)
    if apk["version_code"] != release["androidVersionCode"]:
        cli.error("The APK versionCode must match release-version.json")
    files = [(args.windows, windows(args.windows, name, allow_unsigned=args.allow_unsigned_windows)), (args.android, apk)]
    manifest = {"schema": 2, "tag": args.tag, "notes": notes,
                "date": datetime.now(timezone.utc).date().isoformat(), "artifacts": [item for _, item in files]}
    raw = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    envelope = {"payload": base64.b64encode(raw).decode(),
                "signature": base64.b64encode(key.sign(raw, ec.ECDSA(hashes.SHA256()))).decode()}
    args.output.mkdir(parents=True, exist_ok=False)
    for source, item in files:
        destination = shutil.copyfile(source, args.output / item["name"])
        if artifact(Path(destination), name, item["platform"], item["arch"])["sha256"] != item["sha256"]:
            raise ValueError("Artifact changed during staging")
    (args.output / "SHA256SUMS.txt").write_text(
        "".join(f'{item["sha256"]}  {item["name"]}\n' for _, item in files), encoding="ascii")
    (args.output / "CHANGELOG.md").write_text(notes + "\n", encoding="utf-8")
    (args.output / MANIFEST).write_text(json.dumps(envelope) + "\n", encoding="ascii")
    print(f"Verified assets staged in {args.output}.")


if __name__ == "__main__":
    main()
