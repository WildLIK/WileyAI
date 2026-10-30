"""Host SQLite checks of the Android schema; do not replace on-device tests."""
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "android/app/src/main/java/ru/wildlik/wileyai/mobile"


def open_history(path):
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def create_history(path):
    connection = open_history(path)
    schema = (SOURCE / "LocalChatRepository.java").read_text(encoding="utf-8")
    for name in ("CHATS", "MESSAGES", "INDEX"):
        statement = re.search(rf'static final String {name} = "([^"]+)";', schema)[1]
        connection.execute(statement)
    connection.commit()
    return connection


def test_phone_history_survives_reopen_and_delete_is_isolated(tmp_path):
    path = tmp_path / "phone.db"
    with create_history(path) as connection:
        connection.executemany("INSERT INTO chats(id,title,updated) VALUES(?,?,?)", [("a", "Первый чат", 1), ("b", "Второй чат", 2)])
        connection.executemany("INSERT INTO messages(chat_id,role,content,created) VALUES(?,?,?,?)", [("a", "user", "Громкость 50", 1), ("b", "assistant", "Сохранено", 2)])
        connection.execute("UPDATE chats SET draft=?,title=? WHERE id=?", ("Черновик 👋", "Переименованный", "a"))
    connection.close()
    with open_history(path) as connection:
        assert connection.execute("SELECT title,draft FROM chats WHERE id='a'").fetchone() == ("Переименованный", "Черновик 👋")
        assert connection.execute("SELECT content FROM messages WHERE chat_id='a'").fetchone() == ("Громкость 50",)
        connection.execute("DELETE FROM chats WHERE id='a'")
        assert connection.execute("SELECT chat_id,content FROM messages").fetchall() == [("b", "Сохранено")]
    connection.close()


@pytest.mark.parametrize("chat_id,role", [("missing", "user"), ("a", "system")])
def test_schema_rejects_orphans_and_invalid_roles_without_data_loss(tmp_path, chat_id, role):
    connection = create_history(tmp_path / "phone.db")
    try:
        with connection:
            connection.execute("INSERT INTO chats(id,title,updated) VALUES('a','Сохранить',1)")
        with pytest.raises(sqlite3.IntegrityError), connection:
            connection.execute("UPDATE chats SET title='Не должно остаться' WHERE id='a'")
            connection.execute("INSERT INTO messages(chat_id,role,content,created) VALUES(?,?,?,1)", (chat_id, role, "Не сохранено"))
        assert connection.execute("SELECT title FROM chats").fetchone() == ("Сохранить",)
        assert connection.execute("SELECT count(*) FROM messages").fetchone() == (0,)
    finally:
        connection.close()


def test_gateway_v1_to_v2_history_migration_keeps_data_and_deduplicates_recovery(tmp_path):
    connection = create_history(tmp_path / "phone.db")
    try:
        connection.execute("INSERT INTO chats(id,title,draft,updated) VALUES('a','Сохранить','Черновик',1)")
        connection.execute("INSERT INTO messages(chat_id,role,content,created) VALUES('a','user','Вопрос',1)")
        # Execute the same additive migration on a v1 database with existing history.
        source = (SOURCE / "LocalChatRepository.java").read_text(encoding="utf-8")
        connection.execute(re.search(r'static final String RECOVERIES = "([^"]+)";', source)[1])
        for _ in range(2):
            inserted = connection.execute("INSERT OR IGNORE INTO gateway_recoveries(run_id,chat_id) VALUES('same-run','a')").rowcount
            if inserted:
                connection.execute("INSERT INTO messages(chat_id,role,content,created) VALUES('a','assistant','Ответ',2)")
        assert connection.execute("SELECT content FROM messages ORDER BY id").fetchall() == [("Вопрос",), ("Ответ",)]
        assert connection.execute("SELECT title,draft FROM chats").fetchone() == ("Сохранить", "Черновик")
        connection.execute("DELETE FROM chats WHERE id='a'")
        assert connection.execute("SELECT count(*) FROM gateway_recoveries").fetchone() == (0,)
    finally:
        connection.close()


def test_mobile_theme_tokens_match_desktop_palette():
    css = (ROOT / "src/themes.css").read_text(encoding="utf-8")
    java = (SOURCE / "WileyTheme.java").read_text(encoding="utf-8")
    tokens = ["surface-base", "surface-low", "surface-mid", "surface-high", "text-main", "text-secondary", "text-muted", "accent", "accent-text", "accent-ink", "border"]
    for theme in ("aurora", "ice", "ember", "nebula"):
        selector = r":root \{" if theme == "aurora" else rf':root\[data-theme="{theme}"\] \{{'
        palette = re.search(selector + r"(.*?)\n\}", css, re.S)[1]
        expected = [re.search(rf"--{token}: (#[a-fA-F0-9]{{6}});", palette)[1].lower() for token in tokens]
        case = r"default" if theme == "aurora" else rf'case "{theme}"'
        actual = re.findall(r"#[a-fA-F0-9]{6}", re.search(case + r" -> new WileyTheme\((.*?)\)", java)[1])
        assert actual == expected


def test_dialog_theme_colors_match_desktop_palette():
    css = (ROOT / "src/themes.css").read_text(encoding="utf-8")
    styles = ET.parse(ROOT / "android/app/src/main/res/values/styles.xml").getroot()
    for theme in ("aurora", "ice", "ember", "nebula"):
        selector = r":root \{" if theme == "aurora" else rf':root\[data-theme="{theme}"\] \{{'
        palette = dict(re.findall(r"--([a-z-]+): (#[a-fA-F0-9]{6});", re.search(selector + r"(.*?)\n\}", css, re.S)[1]))
        style = styles.find(f"style[@name='WileyDialog.{theme.title()}']")
        assert style is not None
        items = {item.attrib["name"]: item.text for item in style.findall("item")}
        assert items["android:colorAccent"] == palette["accent-text"]
        assert items["android:textColorPrimary"] == palette["text-main"]
        assert items["android:textColorSecondary"] == palette["text-secondary"]
        assert items["android:colorBackground"] == palette["surface-low"]
