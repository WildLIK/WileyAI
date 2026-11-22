"""Production-generated grammars checked by the pinned real llama.cpp parser.

Build tests/android/c8_grammar_parser.cpp against the pinned llama/ggml libraries
and set WILEY_LLAMA_GRAMMAR_PROBE, or use local/review/c8a-parser/parser.exe.
These host checks do not perform model inference or Android actions.
"""
from pathlib import Path
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'android/app/src/main/java/ru/wildlik/wileyai/mobile'


@pytest.fixture(scope='module')
def grammar_tools(tmp_path_factory):
    parser = Path(os.environ.get('WILEY_LLAMA_GRAMMAR_PROBE', ROOT / 'local/review/c8a-parser/parser.exe'))
    java, javac = shutil.which('java'), shutil.which('javac')
    if not parser.is_file() or not java or not javac:
        pytest.skip('Pinned llama.cpp grammar probe and JDK are required')
    directory = tmp_path_factory.mktemp('c8a-grammar')
    files = [SOURCE / name for name in ('StrictJson.java', 'AndroidTools.java', 'ToolRun.java', 'StructuredActionAdapter.java')]
    files.append(ROOT / 'tests/android/C8GrammarProbe.java')
    subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(directory), *map(str, files)], check=True, capture_output=True)
    grammars = {}
    for name in ('empty', 'one', 'multiple'):
        generated = subprocess.run([java, '-cp', str(directory), 'C8GrammarProbe', name], check=True, capture_output=True)
        path = directory / (name + '.gbnf')
        path.write_bytes(generated.stdout)
        grammars[name] = path
    return parser, grammars


EMPTY = '{"steps":[],"reply":"ok"}'
GET_TIME = '{"steps":[{"tool":"get_time","arguments":{}}],"reply":""}'
SET_VOLUME = '{"steps":[{"tool":"set_volume","arguments":{"percent":30}}],"reply":""}'
UNKNOWN = '{"steps":[{"tool":"open_app","arguments":{"app_name":"x"}}],"reply":""}'


@pytest.mark.parametrize(('grammar', 'sample', 'expected'), [
    ('empty', EMPTY, 'ACCEPT'), ('empty', GET_TIME, 'REJECT'),
    ('empty', UNKNOWN, 'REJECT'), ('one', EMPTY, 'ACCEPT'),
    ('one', GET_TIME, 'ACCEPT'), ('one', SET_VOLUME, 'REJECT'),
    ('one', UNKNOWN, 'REJECT'), ('multiple', EMPTY, 'ACCEPT'),
    ('multiple', GET_TIME, 'ACCEPT'), ('multiple', SET_VOLUME, 'ACCEPT'),
    ('multiple', UNKNOWN, 'REJECT'),
])
def test_real_llama_grammar(grammar_tools, grammar, sample, expected):
    parser, grammars = grammar_tools
    result = subprocess.run([str(parser), str(grammars[grammar]), sample], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
