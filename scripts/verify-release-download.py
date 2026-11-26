"""Verify a downloaded installer against the release manifest and source trust pin."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.signed_updates import verify_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("file", type=Path, nargs="+")
    args = parser.parse_args()
    trust = json.loads((ROOT / "docs/updates/release-trust.json").read_text(encoding="utf-8"))
    manifest = verify_manifest(json.loads(args.manifest.read_bytes()), trust["manifest_p256_spki"], args.tag)
    for file in args.file:
        candidates = [item for item in manifest["artifacts"] if item["name"] == file.name]
        if len(candidates) != 1 or file.stat().st_size != candidates[0]["size"]:
            raise SystemExit("File name or length does not match the signed manifest")
        item = candidates[0]
        if item["platform"] == "android" and item["signer_sha256"] != trust["android_certificate_sha256"]:
            raise SystemExit("Android certificate fingerprint differs from the source trust pin")
        with file.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != item["sha256"]:
                raise SystemExit("SHA-256 differs from the signed manifest")
        print(f"{file.name}: signed manifest and SHA-256 verified")


if __name__ == "__main__":
    main()
