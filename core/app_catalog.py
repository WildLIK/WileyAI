"""Known application names and local install hints, without filesystem access."""
from dataclasses import dataclass
import re


CATEGORIES = {"music": "Музыка", "video": "Видео", "work": "Графика и работа", "messengers": "Мессенджеры", "browsers": "Браузеры", "windows": "Программы Windows"}


@dataclass(frozen=True)
class AppSpec:
    id: str
    category: str
    name: str
    aliases: tuple[str, ...]
    executables: tuple[str, ...]
    locations: tuple[str, ...]


def pf(*paths):
    return tuple(base + "/" + path for base in ("%ProgramFiles%", "%ProgramFiles(x86)%", "%LOCALAPPDATA%/Programs") for path in paths)


def app(key, category, name, aliases, exes, *locations):
    return AppSpec(key, category, name, tuple(aliases.split("|")), tuple(exes.split("|")), tuple(locations))


CATALOG = (
    app("aimp", "music", "AIMP", "аимп|эймп", "AIMP.exe", *pf("AIMP/AIMP.exe")),
    app("yandex-music", "music", "Яндекс Музыка", "яндекс музыку|яндексмузыка|yandex music|yandexmusic", "Яндекс Музыка.exe|ЯндексМузыка.exe|YandexMusic.exe", *pf("YandexMusic/Яндекс Музыка.exe", "YandexMusic/ЯндексМузыка.exe", "YandexMusic/YandexMusic.exe")),
    app("spotify", "music", "Spotify", "спотифай", "Spotify.exe", "%APPDATA%/Spotify/Spotify.exe", *pf("Spotify/Spotify.exe")),
    app("foobar", "music", "foobar2000", "фубар|foobar", "foobar2000.exe", *pf("foobar2000/foobar2000.exe")),
    app("vlc", "video", "VLC", "влс|ви эл си|vlc media player", "vlc.exe", *pf("VideoLAN/VLC/vlc.exe")),
    app("mpc", "video", "MPC-HC", "mpc hc|мпс|media player classic", "mpc-hc64.exe|mpc-hc.exe", *pf("MPC-HC/mpc-hc64.exe", "MPC-HC/mpc-hc.exe")),
    app("potplayer", "video", "PotPlayer", "потплеер|pot player", "PotPlayerMini64.exe|PotPlayerMini.exe", *pf("DAUM/PotPlayer/PotPlayerMini64.exe", "DAUM/PotPlayer/PotPlayerMini.exe")),
    app("kmplayer", "video", "KMPlayer", "кмплеер|км плеер", "KMPlayer.exe|KMPlayer64.exe", *pf("KMPlayer/KMPlayer.exe", "KMPlayer 64X/KMPlayer64.exe")),
    app("photoshop", "work", "Adobe Photoshop", "photoshop|фотошоп|адоб фотошоп", "Photoshop.exe", *pf("Adobe/Adobe Photoshop */Photoshop.exe")),
    app("illustrator", "work", "Adobe Illustrator", "illustrator|иллюстратор", "Illustrator.exe", *pf("Adobe/Adobe Illustrator */Support Files/Contents/Windows/Illustrator.exe")),
    app("gimp", "work", "GIMP", "гимп", "gimp-3.0.exe|gimp-2.10.exe", *pf("GIMP */bin/gimp-3.0.exe", "GIMP */bin/gimp-2.10.exe")),
    app("krita", "work", "Krita", "крита", "krita.exe", *pf("Krita (x64)/bin/krita.exe")),
    app("blender", "work", "Blender", "блендер", "blender.exe", *pf("Blender Foundation/Blender */blender.exe")),
    app("vscode", "work", "Visual Studio Code", "vs code|vscode|code|вс код|ви эс код", "Code.exe", *pf("Microsoft VS Code/Code.exe")),
    app("word", "work", "Microsoft Word", "word|ворд", "WINWORD.EXE", *pf("Microsoft Office/root/Office16/WINWORD.EXE")),
    app("excel", "work", "Microsoft Excel", "excel|эксель", "EXCEL.EXE", *pf("Microsoft Office/root/Office16/EXCEL.EXE")),
    app("powerpoint", "work", "Microsoft PowerPoint", "powerpoint|пауэрпоинт", "POWERPNT.EXE", *pf("Microsoft Office/root/Office16/POWERPNT.EXE")),
    app("telegram", "messengers", "Telegram", "телеграм|телеграмм|telegram desktop", "Telegram.exe", "%APPDATA%/Telegram Desktop/Telegram.exe", "%LOCALAPPDATA%/Telegram Desktop/Telegram.exe", *pf("Telegram Desktop/Telegram.exe")),
    app("discord", "messengers", "Discord", "дискорд", "Discord.exe", "%LOCALAPPDATA%/Discord/app-*/Discord.exe"),
    app("whatsapp", "messengers", "WhatsApp", "ватсап|ватсапп|вотсап", "WhatsApp.exe", "%LOCALAPPDATA%/WhatsApp/WhatsApp.exe"),
    app("viber", "messengers", "Viber", "вайбер", "Viber.exe", "%LOCALAPPDATA%/Viber/Viber.exe"),
    app("chrome", "browsers", "Google Chrome", "chrome|хром|гугл хром", "chrome.exe", "%LOCALAPPDATA%/Google/Chrome/Application/chrome.exe", *pf("Google/Chrome/Application/chrome.exe")),
    app("yandex-browser", "browsers", "Яндекс Браузер", "yandex browser|яндекс браузер|браузер яндекс|яндекс праузер|яндекс броузер", "browser.exe", "%LOCALAPPDATA%/Yandex/YandexBrowser/Application/browser.exe", *pf("Yandex/YandexBrowser/Application/browser.exe")),
    app("firefox", "browsers", "Mozilla Firefox", "firefox|мозилла|мозиллу|мозила|мозилу|файрфокс|mozilla", "firefox.exe", *pf("Mozilla Firefox/firefox.exe")),
    app("edge", "browsers", "Microsoft Edge", "edge|эдж|эдж браузер|майкрософт эдж", "msedge.exe", *pf("Microsoft/Edge/Application/msedge.exe")),
    app("opera", "browsers", "Opera", "опера|оперу|opera browser", "opera.exe", *pf("Opera/launcher.exe")),
    app("terminal", "windows", "Терминал Windows", "windows terminal|terminal|терминал", "wt.exe", "%LOCALAPPDATA%/Microsoft/WindowsApps/wt.exe"),
    *[app(key, "windows", name, aliases, exe, "%WINDIR%/" + relative) for key, name, aliases, exe, relative in (
        ("notepad", "Блокнот", "notepad", "notepad.exe", "System32/notepad.exe"),
        ("calc", "Калькулятор", "calculator|calc", "calc.exe", "System32/calc.exe"),
        ("explorer", "Проводник", "explorer", "explorer.exe", "explorer.exe"),
        ("paint", "Paint", "пейнт|паинт", "mspaint.exe", "System32/mspaint.exe"),
        ("snipping", "Ножницы", "snipping tool|snippingtool", "SnippingTool.exe", "System32/SnippingTool.exe"),
        ("taskmgr", "Диспетчер задач", "task manager|taskmgr", "Taskmgr.exe", "System32/Taskmgr.exe"),
        ("control", "Панель управления", "control panel", "control.exe", "System32/control.exe"),
        ("settings", "Параметры Windows", "параметры|windows settings", "SystemSettings.exe", "ImmersiveControlPanel/SystemSettings.exe"),
        ("charmap", "Таблица символов", "charmap|character map", "charmap.exe", "System32/charmap.exe"),
        ("osk", "Экранная клавиатура", "on screen keyboard|osk", "osk.exe", "System32/osk.exe"),
        ("cmd", "Командная строка", "cmd|command prompt", "cmd.exe", "System32/cmd.exe"),
        ("powershell", "Windows PowerShell", "powershell|пауэршелл", "powershell.exe", "System32/WindowsPowerShell/v1.0/powershell.exe"),
    )],
)


def name_key(value):
    return re.sub(r"\s+", " ", value.casefold().replace("ё", "е").replace("яндекс.", "яндекс ").replace(",", " ")).strip(" .!")


APP_NAMES = {name_key(label): spec.name for spec in CATALOG for label in (spec.name, *spec.aliases)}


def canonical_name(value):
    value = name_key(value)
    return APP_NAMES.get(value) or APP_NAMES.get(re.sub(r"^(?:плеер|браузер|мессенджер|редактор)\s+", "", value))


def shortcut_spec(stem):
    value = re.sub(r"(?:\s+(?:20\d\d(?:\.\d+)*|\d+(?:\.\d+)+|x64|x86|64[- ]bit|32[- ]bit)|\s*\((?:x64|x86|64[- ]bit|32[- ]bit)\))+$", "", name_key(stem))
    name = canonical_name(value)
    return next((spec for spec in CATALOG if spec.name == name), None)
