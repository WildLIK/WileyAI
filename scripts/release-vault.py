"""Initialize and use WileyAI's Windows-only release credentials."""

import argparse
import base64
import csv
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import getpass
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
from zipfile import ZipFile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
ALIAS = "wileyai-release"
BACKUP_HEADER = b"WILEYAI-SIGNING-BACKUP-1\n"


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(payload, *, protect):
    crypt = ctypes.WinDLL("crypt32.dll", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    kernel.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel.LocalFree.restype = wintypes.HLOCAL
    fn = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    fn.argtypes = (ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob))
    fn.restype = wintypes.BOOL
    buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
    source, result = Blob(len(payload), buffer), Blob()
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        ctypes.memset(result.data, 0, result.size)
        kernel.LocalFree(ctypes.cast(result.data, wintypes.HLOCAL))


def private_acl(path, *, directory=True):
    system = Path(os.environ["SystemRoot"]) / "System32"
    identity = subprocess.check_output([str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"], text=True)
    sid = next(csv.reader(identity.splitlines()))[1]
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise ValueError("Cannot identify the signing account")
    access = "(OI)(CI)(F)" if directory else "(F)"
    subprocess.run([str(system / "icacls.exe"), str(path), "/inheritance:r",
                    "/grant:r", f"*{sid}:{access}"], check=True, stdout=subprocess.DEVNULL)


def locations(keystore):
    if not keystore.is_absolute() or keystore.suffix != ".keystore":
        raise ValueError("Use an absolute .keystore path outside the repository")
    path = keystore.resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("The Android key must stay outside the repository")
    return path, path.with_name(path.stem + ".vault")


def initialize(keystore, vault):
    if os.path.lexists(keystore) or os.path.lexists(vault):
        raise FileExistsError("A WileyAI signing path already exists. Existing keys were left intact.")
    if not vault.parent.is_dir():
        raise ValueError("Create the designated external secrets directory first")
    stage = Path(tempfile.mkdtemp(prefix=".wileyai-signing-", dir=vault.parent))
    private_acl(stage)
    keys = {"android": secrets.token_urlsafe(40), "manifest": secrets.token_urlsafe(40)}
    android_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WileyAI Android Release")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(android_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=12775))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(android_key, hashes.SHA256()))
    temp_keystore = stage / keystore.name
    temp_keystore.write_bytes(pkcs12.serialize_key_and_certificates(
        ALIAS.encode(), android_key, cert, None, serialization.BestAvailableEncryption(keys["android"].encode())))
    manifest_key = ec.generate_private_key(ec.SECP256R1())
    (stage / "manifest.pem").write_bytes(manifest_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(keys["manifest"].encode())))
    (stage / "credentials.dpapi").write_bytes(dpapi(json.dumps(keys).encode(), protect=True))
    (stage / "android-cert-sha256.txt").write_text(cert.fingerprint(hashes.SHA256()).hex() + "\n", encoding="ascii")
    public = manifest_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    (stage / "manifest.spki").write_bytes(base64.b64encode(public) + b"\n")
    # Protect the file itself so it cannot inherit permissions from the target directory.
    private_acl(temp_keystore, directory=False)
    temp_keystore.rename(keystore)
    stage.rename(vault)


def environment(keystore, vault, purpose):
    env = {**os.environ, "WILEYAI_UPDATE_PUBLIC_KEY": (vault / "manifest.spki").read_text(encoding="ascii").strip()}
    if purpose == "public":
        return env
    keys = json.loads(dpapi((vault / "credentials.dpapi").read_bytes(), protect=False))
    if purpose == "android":
        env.update(WILEYAI_ANDROID_RELEASE_STORE=str(keystore), WILEYAI_ANDROID_STORE_PASSWORD=keys["android"],
                   WILEYAI_ANDROID_KEY_ALIAS=ALIAS, WILEYAI_ANDROID_KEY_PASSWORD=keys["android"])
    else:
        env.update(WILEYAI_MANIFEST_KEY=str(vault / "manifest.pem"), WILEYAI_MANIFEST_PASSWORD=keys["manifest"],
                   WILEYAI_ANDROID_RELEASE_SIGNER=(vault / "android-cert-sha256.txt").read_text(encoding="ascii").strip())
    return env


def backup(keystore, vault, target):
    target = target.resolve()
    if target.is_relative_to(ROOT):
        raise ValueError("Keep the encrypted backup outside the repository")
    password = getpass.getpass("Recovery passphrase: ")
    if len(password) < 16 or getpass.getpass("Repeat recovery passphrase: ") != password:
        raise ValueError("Use a matching recovery passphrase of at least 16 characters")
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.write(keystore, keystore.name)
        for name in ("manifest.pem", "manifest.spki", "android-cert-sha256.txt"):
            archive.write(vault / name, name)
        archive.writestr("credentials.json", dpapi((vault / "credentials.dpapi").read_bytes(), protect=False))
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    key = Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password.encode())
    with target.open("xb") as file:
        file.write(BACKUP_HEADER + salt + nonce + AESGCM(key).encrypt(nonce, buffer.getvalue(), BACKUP_HEADER))


def restore(keystore, vault, source):
    if os.path.lexists(keystore) or os.path.lexists(vault):
        raise FileExistsError("Restore requires unused paths. Existing keys were left intact.")
    with source.open("rb") as file:
        if file.read(len(BACKUP_HEADER)) != BACKUP_HEADER:
            raise ValueError("Unrecognized WileyAI signing backup")
        salt, nonce, ciphertext = file.read(16), file.read(12), file.read(128 * 1024 + 1)
    if len(ciphertext) > 128 * 1024:
        raise ValueError("Signing backup exceeds the expected size")
    password = getpass.getpass("Recovery passphrase: ").encode()
    key = Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password)
    clear = AESGCM(key).decrypt(nonce, ciphertext, BACKUP_HEADER)
    with ZipFile(io.BytesIO(clear)) as archive:
        names = {entry.filename for entry in archive.infolist()}
        expected = {"credentials.json", "manifest.pem", "manifest.spki", "android-cert-sha256.txt"}
        android_names = names - expected
        if (not expected.issubset(names) or len(android_names) != 1 or len(archive.infolist()) != len(names)
                or any(entry.file_size > 65536 for entry in archive.infolist())):
            raise ValueError("Unexpected signing backup layout")
        android_name = android_names.pop()
        if not re.fullmatch(r"[A-Za-z0-9._-]+\.keystore", android_name):
            raise ValueError("Unexpected keystore name in backup")
        materials = {name: archive.read(name) for name in expected}
        android = archive.read(android_name)
    keys = json.loads(materials.pop("credentials.json"))
    p12 = pkcs12.load_pkcs12(android, keys["android"].encode())
    manifest = serialization.load_pem_private_key(materials["manifest.pem"], keys["manifest"].encode())
    public = manifest.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if (p12.key is None or p12.cert is None or p12.cert.friendly_name != ALIAS.encode()
            or p12.cert.certificate.fingerprint(hashes.SHA256()).hex() != materials["android-cert-sha256.txt"].decode().strip()
            or not isinstance(manifest, ec.EllipticCurvePrivateKey) or not isinstance(manifest.curve, ec.SECP256R1)
            or public != base64.b64decode(materials["manifest.spki"])):
        raise ValueError("The key and public trust fingerprints in the backup disagree")
    stage = Path(tempfile.mkdtemp(prefix=".wileyai-recovery-", dir=vault.parent))
    private_acl(stage)
    for name, value in materials.items():
        (stage / name).write_bytes(value)
    (stage / "credentials.dpapi").write_bytes(dpapi(json.dumps(keys).encode(), protect=True))
    temporary = stage / keystore.name
    temporary.write_bytes(android)
    private_acl(temporary, directory=False)
    temporary.rename(keystore)
    stage.rename(vault)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keystore", type=Path, default=Path("D:/secrets/wileyai-release.keystore"))
    sub = parser.add_subparsers(dest="task", required=True)
    sub.add_parser("init")
    sub.add_parser("fingerprints")
    launch = sub.add_parser("run")
    launch.add_argument("purpose", choices=("public", "android", "manifest"))
    launch.add_argument("command", nargs=argparse.REMAINDER)
    export = sub.add_parser("backup")
    export.add_argument("file", type=Path)
    recovery = sub.add_parser("restore")
    recovery.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    if os.name != "nt":
        parser.error("WileyAI signing vault requires Windows DPAPI")
    keystore, vault = locations(args.keystore)
    if args.task == "init":
        initialize(keystore, vault)
        print("Created separate encrypted WileyAI signing credentials.")
    elif args.task == "run":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            parser.error("A trusted command is required")
        return subprocess.run(command, env=environment(keystore, vault, args.purpose)).returncode
    elif args.task == "backup":
        backup(keystore, vault, args.file)
        print("Encrypted backup saved.")
    elif args.task == "restore":
        restore(keystore, vault, args.file)
        print("Keys restored into new protected paths.")
    else:
        raw = base64.b64decode((vault / "manifest.spki").read_bytes())
        from hashlib import sha256
        print("Android SHA-256:", (vault / "android-cert-sha256.txt").read_text().strip())
        print("Manifest SPKI SHA-256:", sha256(raw).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
