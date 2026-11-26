"""Fail closed on private files, unreviewed model weights and missing notices."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from zipfile import ZipFile

VAD = "2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f"
PRIVATE = re.compile(
    r"(?:^|/)(?:\.env(?:\..*)?|credentials\.dpapi|wake-research-assets|wake-stage1|wake-next16|"
    r"research-audio|process-faults\.json)(?:/|$)|\.(?:pfx|p12|jks|keystore|pem|sqlite3?|flac|wav|gguf|safetensors)$",
    re.I,
)
APK_REQUIRED = {
    "assets/licenses/APACHE-2.0.txt", "assets/licenses/JNA-LICENSE.txt", "assets/licenses/VOSK-COPYING.txt",
    "assets/licenses/ONEST-OFL.txt", "assets/licenses/llama-cpp-MIT.txt",
    "assets/licenses/NOTICE.txt", "assets/voice-vad/silero_vad_v5.onnx",
    "assets/voice-vad/THIRD_PARTY_NOTICES.md",
}


def check_names(names, allowed_models):
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or PRIVATE.search(name):
            raise ValueError(f"Private or unsafe release member: {name}")
        if path.suffix.lower() in {".onnx", ".tflite", ".pt", ".pth", ".binmodel"} and name not in allowed_models:
            raise ValueError(f"Unreviewed model: {name}")


def android_assets(apk):
    allowed_model = "assets/voice-vad/silero_vad_v5.onnx"
    with ZipFile(apk) as bundle:
        names = set(bundle.namelist())
        check_names(names, {allowed_model})
        if missing := APK_REQUIRED - names:
            raise ValueError("APK missing public assets and notices: " + ", ".join(sorted(missing)))
        if hashlib.sha256(bundle.read(allowed_model)).hexdigest() != VAD:
            raise ValueError("Unexpected Silero VAD bytes")
        if "lib/arm64-v8a/libsherpa-onnx-jni.so" in names:
            notices = {"assets/voice-vad/ONNX-Runtime-LICENSE.txt", "assets/voice-vad/ONNX-Runtime-ThirdPartyNotices.txt"}
            if missing := notices - names:
                raise ValueError("APK missing native runtime notices: " + ", ".join(sorted(missing)))
        return len(names)


def windows_assets(folder):
    names = {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}
    ca_bundles = {"resources/runtime/python/Lib/site-packages/certifi/cacert.pem",
                  "resources/runtime/python/Lib/site-packages/pip/_vendor/certifi/cacert.pem"}
    for ca_bundle in names & ca_bundles:
        data = (folder / ca_bundle).read_bytes()
        if b"PRIVATE KEY" in data or b"-----BEGIN CERTIFICATE-----" not in data:
            raise ValueError("Invalid public CA bundle from certifi")
    check_names(names - ca_bundles, set())
    probe = """
    const asar = require('@electron/asar'), crypto = require('node:crypto'), path = require('node:path');
    const file = process.argv[1], entries = asar.listPackage(file).map(p => p.replaceAll('\\\\', '/').replace(/^\\//,''));
    const models = entries.filter(p => /\\.(onnx|tflite|pt|pth|binmodel)$/i.test(p));
    const digests = models.map(p => crypto.createHash('sha256').update(asar.extractFile(file,path.normalize(p))).digest('hex'));
    console.log(JSON.stringify({entries,models,digests}));
    """
    app = json.loads(subprocess.check_output(["node", "-e", probe, str(folder / "resources/app.asar")], text=True,
                                            cwd=Path(__file__).resolve().parents[1]))
    if (len(app["models"]) != 1 or not app["models"][0].startswith("dist/assets/silero_vad_v5-")
            or app["digests"] != [VAD]):
        raise ValueError("Unexpected model content in Windows application")
    check_names(app["entries"], set(app["models"]))
    notices = {"LICENSE.electron.txt", "LICENSES.chromium.html", "resources/THIRD_PARTY_NOTICES.md",
               "resources/runtime/python/LICENSE.txt", "resources/licenses/onnxruntime-web-LICENSE.txt",
               "resources/licenses/react-LICENSE.txt", "resources/licenses/voice/ONNX-Runtime-ThirdPartyNotices.txt"}
    if missing := notices - names:
        raise ValueError("Windows package missing notices: " + ", ".join(sorted(missing)))
    return len(names) + len(app["entries"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android", type=Path, required=True)
    parser.add_argument("--windows-dir", type=Path, required=True)
    args = parser.parse_args()
    print("APK reviewed entries:", android_assets(args.android))
    print("Windows reviewed files:", windows_assets(args.windows_dir))


if __name__ == "__main__":
    main()
