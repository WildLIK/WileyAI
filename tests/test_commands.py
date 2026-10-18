from pathlib import Path
import pytest

from core.commands import Command, execute, normalize, resolve, validate, opening_target


@pytest.mark.parametrize("text", [
    "Не открывай браузер", "Не открой браузер", "Как открыть браузер?",
    "Открой браузер?", 'Мне сказали "открой браузер"', "Пожалуйста, не открывай загрузки",
    "Открой «загрузки»", "Открой загрузки\nи удали файлы", "Открой powershell -Command whoami",
])
def test_non_commands_never_execute(text):
    assert resolve(text, []) is None


@pytest.mark.parametrize("text", ["Открой загрузки", "пожалуйста, открой загрузки", "Открой загрузки, пожалуйста."])
def test_folder_command_variations(text):
    command = resolve(text, [])
    assert command is not None and command.kind == "folder"


def test_custom_alias_and_case_preserved(tmp_path):
    path = tmp_path / "Отчёт.DOCX"
    path.touch()
    aliases = [{"name": "отчёт", "kind": "file", "target": str(path)}]
    command = resolve("Открой файл отчёт", aliases)
    assert command.target == str(path)
    assert "Запуск не выполнялся" in execute(command, dry_run=True)


@pytest.mark.parametrize("target", ["file:///C:/windows/system32/calc.exe", "javascript:alert(1)", "https://user:password@example.com", "https://"])
def test_url_validation_rejects_unsafe_schemes_and_credentials(target):
    with pytest.raises(ValueError):
        validate(Command("url", target, "сайт"))


def test_executable_cannot_be_opened_as_document(tmp_path):
    file = tmp_path / "script.ps1"
    file.touch()
    with pytest.raises(ValueError, match="Исполняемый"):
        validate(Command("file", str(file), "скрипт"))


def test_missing_target_does_not_claim_success(tmp_path):
    with pytest.raises(ValueError, match="не найдены"):
        execute(Command("file", str(tmp_path / "missing.txt"), "missing"), dry_run=True)


def test_url_and_known_site():
    assert resolve("Открой гитхаб", []).target == "https://github.com"
    assert resolve("Открой https://example.com/MyPage?q=1", []).target == "https://example.com/MyPage?q=1"


@pytest.mark.parametrize("text,expected", [
    ("Открой мне сайт YouTube.", "https://www.youtube.com"),
    ("Открой мне сайт GitHub.", "https://github.com"),
    ("Открой кит-хаб.", "https://github.com"),
    ("Открой мне гит хаб", "https://github.com"),
    ("Можешь открыть мне GitHub?", "https://github.com"),
    ("Ты можешь, пожалуйста, открыть мне GitHub?", "https://github.com"),
    ("Пожалуйста, открой мне сайт YouTube.", "https://www.youtube.com"),
    ("Открой мне сайт https://example.com/MyPage?q=One", "https://example.com/MyPage?q=One"),
    ("Открой мне example.com/MyPage", "https://example.com/MyPage"),
])
def test_natural_opening_variants(text, expected):
    command = resolve(text, [])
    assert command is not None and command.kind == "url" and command.target == expected


@pytest.mark.parametrize("text", ["Открой.", "Открой, открой, открой, открой.", "открой открой"])
def test_repeated_or_empty_opening_needs_a_target(text):
    assert opening_target(text) == ""
    assert resolve(text, []) is None


def test_natural_opening_preserves_path_case_and_alias_priority(tmp_path):
    path = tmp_path / "Мой Отчёт.DOCX"
    path.touch()
    command = resolve("Открой мне файл " + str(path), [])
    assert command.target == str(path)
    alias = {"name": "кит-хаб", "kind": "url", "target": "https://example.com/Custom"}
    assert resolve("Открой мне кит-хаб", [alias]).target == alias["target"]
