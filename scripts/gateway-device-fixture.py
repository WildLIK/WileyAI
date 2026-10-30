"""Disposable, loopback-only TLS fixture. Never loads a real provider account."""
from pathlib import Path
import datetime
import ipaddress
import json
import secrets

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import uvicorn

from gateway.app import create_app
from gateway.store import Store, new_id

root = Path.cwd()
if not (root / "gateway/app.py").is_file():
    raise SystemExit("Run from the WileyAI repository root")
directory = root / ("local/review/phone-0.10.0/tls-fixture-" + secrets.token_hex(4))
directory.mkdir(parents=True, exist_ok=True)
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WileyAI disposable device test")])
now = datetime.datetime.now(datetime.timezone.utc)
certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=2))
               .not_valid_after(now+datetime.timedelta(days=2))
               .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1")),x509.DNSName("localhost")]),False)
               .add_extension(x509.BasicConstraints(ca=True,path_length=0),True)
               .sign(key,hashes.SHA256()))
certificate_path, key_path = directory/"certificate.pem", directory/"tls.key"
certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
vault_key=secrets.token_bytes(32)
store = Store(directory/"data",vault_key)
token=store.token(new_id())
fixture={"url":"https://127.0.0.1:48593","token":token,"certificate":certificate_path.read_text(encoding="ascii")}
asset=root/"android/app/src/androidTest/assets/gateway-fixture.json"
asset.parent.mkdir(parents=True,exist_ok=True)
asset.write_text(json.dumps(fixture),encoding="utf-8")
control=root/"local/review/phone-0.10.0/fixture-control.json"
control.write_text(json.dumps({"url":"https://127.0.0.1:49793","token":token,"certificate":str(certificate_path)}),encoding="utf-8")
app=create_app(store.root,vault_key,test_mode=True,store=store)
server=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=49793,ssl_keyfile=key_path,ssl_certfile=certificate_path,access_log=False,log_level="warning",ws="none"))
@app.post("/api/v1/fixture-shutdown")
async def shutdown():
    server.should_exit=True
    return {"stopping":True}
print("DEVICE_FIXTURE_READY: loopback HTTPS 49793; Android reverse port 48593",flush=True)
server.run()
