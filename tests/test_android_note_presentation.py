import subprocess
from pathlib import Path

def test_note_presentation(tmp_path):
    source = Path('android/app/src/main/java/ru/wildlik/wileyai/mobile/NotePresentation.java')
    test = tmp_path / 'NoteProbe.java'
    test.write_text('''package ru.wildlik.wileyai.mobile; public class NoteProbe { public static void main(String[] a) { if(!NotePresentation.title("Первая строка\\nДлинный текст").equals("Первая строка"))throw new AssertionError(); if(!NotePresentation.matches("Тестовая ЗАМЕТКА\\nссылка https://example.org", "заметка"))throw new AssertionError(); if(NotePresentation.matches("текст", "чай"))throw new AssertionError(); } }''', encoding='utf-8')
    subprocess.run(['javac','-encoding','UTF-8','-d',str(tmp_path),str(source),str(test)],check=True)
    subprocess.run(['java','-cp',str(tmp_path),'ru.wildlik.wileyai.mobile.NoteProbe'],check=True)
