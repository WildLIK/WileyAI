"""Android's exact JCA verifier with freshly signed test identities. No account tokens or network."""
from pathlib import Path
import json,os,shutil,subprocess,time
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa,ec

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'android/app/src/main/java/ru/wildlik/wileyai/mobile'

@pytest.fixture(scope='module')
def identity_probe(tmp_path_factory):
    binaries=Path(os.environ.get('JAVA_HOME',''))/'bin';javac=str(binaries/'javac.exe') if (binaries/'javac.exe').exists() else shutil.which('javac');java=str(binaries/'java.exe') if (binaries/'java.exe').exists() else shutil.which('java')
    if not javac or not java:pytest.skip('JDK 17 required')
    classes=tmp_path_factory.mktemp('identity-java');files=[SOURCE/x for x in ['StrictJson.java','JwtIdentity.java','ProviderSse.java']]+[ROOT/'tests/android/IdentityProbe.java']
    result=subprocess.run([javac,'-encoding','UTF-8','-d',str(classes),*map(str,files)],capture_output=True,text=True,timeout=30);assert result.returncode==0,result.stdout+result.stderr
    return java,classes

@pytest.mark.parametrize('scenario',['rsa','ec','wrong-nonce','wrong-audience','wrong-issuer','expired','future-issued','wrong-subject','duplicate-key','bad-signature','none-algorithm','expired-before-issued','wrong-key-operation'])
def test_android_oidc_identity(identity_probe,tmp_path,scenario):
    java,classes=identity_probe;now=int(time.time());key=ec.generate_private_key(ec.SECP256R1()) if scenario=='ec' else rsa.generate_private_key(public_exponent=65537,key_size=2048);alg='ES256' if scenario=='ec' else 'RS256'
    jwk=json.loads((jwt.algorithms.ECAlgorithm if scenario=='ec' else jwt.algorithms.RSAAlgorithm).to_jwk(key.public_key()));jwk.update(kid='test-key',use='sig')
    claims={'iss':'https://auth.openai.com','aud':'wiley-own-test','sub':'test-subject','nonce':'test-nonce','iat':now,'exp':now+300}
    if scenario=='wrong-nonce':claims['nonce']='another'
    if scenario=='wrong-audience':claims['aud']='another-client'
    if scenario=='wrong-issuer':claims['iss']='https://attacker.invalid'
    if scenario=='expired':claims['exp']=now-120
    if scenario=='future-issued':claims['iat']=now+3600
    if scenario=='expired-before-issued':claims['exp']=now;claims['iat']=now+1
    if scenario=='wrong-key-operation':jwk['key_ops']=['encrypt']
    token=jwt.encode(claims,key,algorithm=alg,headers={'kid':'test-key'})
    if scenario=='bad-signature':token=token.rsplit('.',1)[0]+'.'+('AA'*100)
    if scenario=='none-algorithm':token=jwt.encode(claims,key='',algorithm='none',headers={'kid':'test-key'})
    fixture={'token':token,'client':'wiley-own-test','nonce':'test-nonce','subject':'other' if scenario=='wrong-subject' else 'test-subject','now':now,'jwks':{'keys':[jwk,jwk] if scenario=='duplicate-key' else [jwk]},'accepted':scenario in {'rsa','ec'}}
    path=tmp_path/'identity.json';path.write_text(json.dumps(fixture),encoding='utf-8');result=subprocess.run([java,'-cp',str(classes),'IdentityProbe',str(path)],capture_output=True,text=True,timeout=10);assert result.returncode==0,result.stdout+result.stderr
