from pathlib import Path
import pytest

from core.commands import Command, execute, normalize, resolve, validate


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
