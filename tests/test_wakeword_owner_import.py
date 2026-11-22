"""Exercise explicit local ZIP import and reject guessed or truncated wake labels."""
import csv
import io
import json
import subprocess
import uuid
import wave
import zipfile
import hashlib
from pathlib import Path

import pytest


def test_owner_import_requires_real_intervals(tmp_path):
    root = Path(__file__).resolve().parents[1]
    python = root / 'local/wakeword26b/venv/Scripts/python.exe'
    script = root / 'local/wakeword26b/prepare_owner_samples.py'
    if not python.exists() or not script.exists():
        pytest.skip('Optional isolated wake-word environment unavailable')
    archive, template = tmp_path / 'samples.zip', tmp_path / 'labels.csv'
    with zipfile.ZipFile(archive, 'w') as z:
        counts = {'train': 0, 'validation': 0, 'test': 0}
        candidates = []
        for index in range(1, 1000):
            name = str(uuid.UUID(int=index))
            h = int(hashlib.sha256(name.encode()).hexdigest()[:8], 16) % 100
            split = 'train' if h < 70 else 'validation' if h < 85 else 'test'
            if counts[split] < 5:
                counts[split] += 1
                candidates.append(name)
            if all(value == 5 for value in counts.values()):
                break
        for name in candidates:
            z.writestr(name + '.json', json.dumps({'id': name, 'phrase': 'Вайли'}))
            b = io.BytesIO()
            with wave.open(b, 'wb') as w:
                w.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                w.writeframes(bytes(64000))
            z.writestr(name + '.wav', b.getvalue())
    run = subprocess.run([str(python), str(script), str(archive), '--template', str(template)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    run = subprocess.run([str(python), str(script), str(archive), '--annotations', str(template)], capture_output=True, text=True, timeout=30)
    assert run.returncode != 0
    with template.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row['wake_start_s'], row['wake_end_s'] = '0.2', '0.7'
    with template.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'phrase', 'wake_start_s', 'wake_end_s'])
        writer.writeheader()
        writer.writerows(rows)
    output = tmp_path / 'features.npz'
    run = subprocess.run([str(python), str(script), str(archive), '--annotations', str(template), '--output', str(output)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0 and output.exists(), run.stderr
    # An overlong annotation must be rejected before any output is written.
    rows[0]['wake_end_s'] = '1.9'
    with template.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'phrase', 'wake_start_s', 'wake_end_s'])
        writer.writeheader()
        writer.writerows(rows)
    run = subprocess.run([str(python), str(script), str(archive), '--annotations', str(template), '--output', str(tmp_path / 'invalid.npz')], capture_output=True, text=True, timeout=30)
    assert run.returncode != 0 and 'longer than' in run.stderr
