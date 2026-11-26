import base64
from pathlib import Path
import shutil
import subprocess

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def test_android_accepts_exact_utf8_bytes_signed_by_release_tool(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK unavailable")
    root = Path(__file__).resolve().parents[1]
    source = root / "android/app/src/main/java/ru/wildlik/wileyai/mobile/UpdateSignature.java"
    probe = root / "tests/android/UpdateSignatureProbe.java"
    subprocess.run([javac, "-encoding", "UTF-8", "-d", str(tmp_path), str(source), str(probe)], check=True)
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    payload = '{"notes":"Проверка","schema":1}'.encode("utf-8")
    signature = key.sign(payload, ec.ECDSA(hashes.SHA256()))
    args = [base64.b64encode(blob).decode() for blob in (public, payload, signature)]
    subprocess.run([java, "-cp", str(tmp_path), "ru.wildlik.wileyai.mobile.UpdateSignatureProbe", *args], check=True)
