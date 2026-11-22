from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
ROOT=Path(__file__).resolve().parents[1]
A="{http://schemas.android.com/apk/res/android}"
def test_single_application_identity_and_private_log_provider():
 p=ROOT/'android/app/build/intermediates/merged_manifests/debug/processDebugManifest/AndroidManifest.xml'
 if not p.exists(): pytest.skip('Build debug first')
 root=ET.parse(p).getroot()
 assert root.get('package')=='ru.wildlik.wileyai.mobile'
 assert root.get(A+'sharedUserId') is None
 provider=root.find("./application/provider[@"+A+"name='ru.wildlik.wileyai.mobile.DiagnosticShareProvider']")
 assert provider is not None
 assert provider.get(A+'authorities')=='ru.wildlik.wileyai.mobile.diagnostics'
 assert provider.get(A+'exported')=='false'
 assert provider.get(A+'grantUriPermissions')=='true'
 gradle=(ROOT/'android/app/build.gradle').read_bytes().decode('cp1251')
 assert 'applicationIdSuffix' not in gradle
