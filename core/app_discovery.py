"""Bounded, read-only Windows app discovery. Scanning never launches anything."""
from dataclasses import dataclass
import glob
import difflib
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import threading
import time
from datetime import datetime, timezone

from .app_catalog import CATALOG, CATEGORIES, shortcut_spec, canonical_name


@dataclass
class Candidate:
    spec_id: str
    path: str
    source: str
    name: str = ""


def full_name(value):
    value = re.sub(r"[\s._-]+", " ", value.casefold().replace("ё", "е")).strip()
    return value


def normalized_name(value):
    return re.sub(r"(?:\s+(?:v?\d+(?:\.\d+)*|20\d\d|x64|x86|64\s*bit|32\s*bit)|\s*\((?:x64|x86|64\s*bit|32\s*bit)\))+$", "", full_name(value)).strip()


_SOUNDS = {"а":"a", "б":"b", "в":"v", "г":"g", "д":"d", "е":"e", "ё":"e", "ж":"zh", "з":"z", "и":"i", "й":"i", "к":"k", "л":"l", "м":"m", "н":"n", "о":"o", "п":"p", "р":"r", "с":"s", "т":"t", "у":"u", "ф":"f", "х":"h", "ц":"ts", "ч":"ch", "ш":"sh", "щ":"sh", "ы":"y", "э":"e", "ю":"yu", "я":"ya", "ь":"", "ъ":""}


def sound_key(value):
    value = normalized_name(value)
    transliterated = "".join(_SOUNDS.get(char, char) for char in value)
    tokens = transliterated.split()
    letter_names = {"vi": "v", "es": "s", "bi": "b", "si": "c", "di": "d", "dzhi": "g", "ei": "a"}
    for index in range(len(tokens) - 1):
        if tokens[index] in letter_names and tokens[index + 1] in letter_names:
            tokens[index], tokens[index + 1] = letter_names[tokens[index]], letter_names[tokens[index + 1]]
    key = "".join(char for char in "".join(tokens) if char.isalnum())
    return key.replace("x", "ks").replace("ai", "i")


def safe_application_name(value):
    name = re.sub(r"[^\w]+", " ", value.casefold().replace("ё", "е")).strip()
    if not name or len(name) > 150:
        return False
    return not re.search(r"(?:^|\s)(?:uninstall(?:er)?|setup|installer|install|unins\d*|update(?:r)?|repair|remove|delete|deinstall|деинсталлятор|удаление|установщик|powershell|pwsh|cmd|regedit|regsvr32|rundll32|msiexec|schtasks|taskkill|diskpart|mmc|wscript|cscript|terminal)(?:\s|$)", name, re.I)


def local_file(value, extensions=(".exe",)):
    if not isinstance(value, str) or not value or value.startswith(("\\\\", "//")):
        return None
    expanded = os.path.expandvars(value.strip().strip('"'))
    if expanded.startswith(("\\\\", "//")):
        return None
    path = Path(expanded)
    if not path.is_absolute() or path.suffix.casefold() not in extensions:
        return None
    try:
        resolved = os.path.realpath(path)
        return path if path.is_file() and not resolved.startswith(("\\\\", "//")) else None
    except (OSError, ValueError):
        return None


def registry_candidates():
    import winreg
    results = []
    deadline = time.monotonic() + 3
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths", 0, winreg.KEY_READ | view) as parent:
                    index = 0
                    while index < 2000 and time.monotonic() < deadline:
                        try: exe = winreg.EnumKey(parent, index)
                        except OSError: break
                        index += 1
                        if not exe.casefold().endswith(".exe") or not safe_application_name(Path(exe).stem):
                            continue
                        try:
                            with winreg.OpenKey(parent, exe, 0, winreg.KEY_READ | view) as opened:
                                value, kind = winreg.QueryValueEx(opened, None)
                            if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                                spec = next((s for s in CATALOG if exe.casefold() in (n.casefold() for n in s.executables)), None)
                                results.append(Candidate(spec.id if spec else "", value, "Регистрация Windows", Path(exe).stem))
                        except OSError:
                            continue
            except OSError:
                continue
    return results


def installed_registry_candidates():
    """Read display names/icons, never uninstall or install commands."""
    import winreg
    results, deadline = [], time.monotonic() + 3
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", 0, winreg.KEY_READ | view) as parent:
                    index = 0
                    while index < 2000 and time.monotonic() < deadline:
                        try: name = winreg.EnumKey(parent, index)
                        except OSError: break
                        index += 1
                        try:
                            with winreg.OpenKey(parent, name, 0, winreg.KEY_READ | view) as entry:
                                label, label_type = winreg.QueryValueEx(entry, "DisplayName")
                                icon, icon_type = winreg.QueryValueEx(entry, "DisplayIcon")
                            if label_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or icon_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) or not isinstance(label, str) or not isinstance(icon, str):
                                continue
                            if not safe_application_name(label):
                                continue
                            match = re.fullmatch(r'\s*("[^"\r\n]+\.exe"|[^"\r\n]+?\.exe)(?:,\s*-?\d+)?\s*', icon, re.I)
                            if not match:
                                continue
                            target = match[1].strip().strip('"')
                            if local_file(target) and safe_application_name(Path(target).stem):
                                results.append(Candidate("", target, "Список установленных программ", label))
                        except (OSError, ValueError, TypeError):
                            continue
            except OSError:
                continue
    return results


def location_candidates():
    results = []
    for spec in CATALOG:
        for hint in spec.locations:
            pattern = os.path.expandvars(hint)
            if "%" in pattern or pattern.startswith(("\\\\", "//")):
                continue
            # Catalog hints have no recursive wildcards: only a product/version folder.
            for index, value in enumerate(glob.iglob(pattern)):
                if index >= 64:
                    break
                results.append(Candidate(spec.id, value, "Папка приложения"))
    # Choose newer version folder names before older ones when no registration exists.
    return sorted(results, key=lambda item: [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", item.path.casefold())], reverse=True)


def menu_links(roots, *, limit=4000, seconds=3):
    found, visited, deadline, limited = [], 0, time.monotonic() + seconds, False
    stack = [(Path(root), 0) for root in roots if str(root) and not str(root).startswith(("\\\\", "//"))]
    while stack and visited < limit and time.monotonic() < deadline:
        folder, depth = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    visited += 1
                    if visited > limit or time.monotonic() >= deadline:
                        limited = True
                        break
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        if depth < 6 and not path.is_junction():
                            stack.append((path, depth + 1))
                    elif entry.is_file(follow_symlinks=False) and path.suffix.casefold() == ".lnk":
                        if safe_application_name(path.stem):
                            found.append((shortcut_spec(path.stem), path))
        except OSError:
            continue
    return found, limited or bool(stack) or visited >= limit


def shortcut_targets(paths):
    """Read shortcut metadata with the built-in Windows COM host; no link is run."""
    if not paths:
        return {}
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = r'''
$ErrorActionPreference='Stop'
[Console]::InputEncoding=[System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$paths=ConvertFrom-Json ([Console]::In.ReadToEnd())
$shell=New-Object -ComObject WScript.Shell
$result=@{}
foreach ($path in $paths) {
  try { $result[$path]=$shell.CreateShortcut($path).TargetPath } catch {}
}
ConvertTo-Json -InputObject $result -Compress
'''
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                            input=json.dumps([str(path) for path in paths], ensure_ascii=False),
                            encoding="utf-8", errors="replace", capture_output=True, timeout=6,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError("Не удалось прочитать часть ярлыков Windows")
    data = json.loads(result.stdout.lstrip("\ufeff"))
    return data if isinstance(data, dict) else {}


def discover():
    if os.name != "nt":
        return {"supported": False, "items": [], "categories": CATEGORIES, "warnings": ["Сканирование доступно в Windows."]}
    candidates, warnings = registry_candidates() + installed_registry_candidates(), []
    candidates += location_candidates()
    roots = [Path(value) / "Microsoft/Windows/Start Menu/Programs" for key in ("APPDATA", "PROGRAMDATA") if (value := os.environ.get(key))]
    links, limited = menu_links(roots)
    if limited:
        warnings.append("Достигнут предел просмотра меню «Пуск»: показаны уже найденные приложения.")
    try:
        targets = shortcut_targets([path for _, path in links])
    except (OSError, ValueError, subprocess.TimeoutExpired):
        targets = {}
        warnings.append("Часть ярлыков не удалось проверить. Остальные результаты доступны.")
    try:
        packaged = packaged_candidates()
    except (OSError, ValueError, subprocess.TimeoutExpired):
        packaged = []
        warnings.append("Не удалось проверить приложения Microsoft Store.")
    # Use the verified executable directly: a shortcut can carry arbitrary arguments.
    linked = [Candidate(spec.id if spec else "", targets.get(str(path), ""), "Ярлык меню «Пуск»", path.stem)
              for spec, path in links if local_file(targets.get(str(path)))]
    items, seen = [], set()
    known = {spec.id: spec for spec in CATALOG}
    for item in [*linked, *candidates, *packaged]:
        if is_packaged_target(item.path):
            identity = item.path.casefold()
            if identity not in seen and safe_application_name(item.name):
                seen.add(identity)
                items.append({"id": hashlib.sha256(identity.encode()).hexdigest()[:24], "name": item.name,
                              "category": "other", "target": item.path, "source": item.source, "aliases": [], "launch_type": "aumid"})
            continue
        path = local_file(item.path)
        if path is None or not safe_application_name(path.stem) or not safe_application_name(Path(os.path.realpath(path)).stem):
            continue
        identity = os.path.normcase(os.path.realpath(path))
        if identity in seen:
            continue
        spec = known.get(item.spec_id)
        name = spec.name if spec else item.name or path.stem
        if spec and item.source == "Ярлык меню «Пуск»" and item.name and normalized_name(item.name) == normalized_name(spec.name) and full_name(item.name) != normalized_name(item.name):
            name = item.name
        if not safe_application_name(name):
            continue
        seen.add(identity)
        items.append({"id": hashlib.sha256(identity.casefold().encode()).hexdigest()[:24],
                      "name": name, "category": spec.category if spec else "other", "target": str(path),
                      "source": item.source, "aliases": list((spec.name, *spec.aliases)) if spec else [], "launch_type": "exe"})
    order = list(CATEGORIES)
    items.sort(key=lambda item: (order.index(item["category"]), item["name"].casefold()))
    return {"supported": True, "items": items, "categories": CATEGORIES, "warnings": warnings}


MISSING_TTL = 300
PACKAGE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,127}_[a-z0-9]{13}![A-Za-z0-9][A-Za-z0-9._-]{0,63}", re.I)


def is_packaged_target(value):
    return isinstance(value, str) and value.startswith("aumid:") and PACKAGE_ID.fullmatch(value[6:]) is not None


def packaged_candidates():
    """Enumerate Start apps whose package family is registered for this user."""
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$families=@{}
Get-AppxPackage | ForEach-Object { $families[$_.PackageFamilyName]=$true }
$items=@(Get-StartApps | Where-Object { $_.AppID -match '^([^!]+)!' -and $families.ContainsKey($Matches[1]) } | Select-Object -First 2000 Name,AppID)
ConvertTo-Json -InputObject $items -Compress
'''
    result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                            encoding="utf-8", errors="replace", capture_output=True, timeout=12,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise ValueError("Не удалось проверить приложения Microsoft Store")
    data = json.loads(result.stdout.lstrip("\ufeff"))
    if not isinstance(data, list) or len(data) > 2000:
        raise ValueError("Не удалось проверить приложения Microsoft Store")
    result = []
    for entry in data:
        if not isinstance(entry, dict): continue
        name, appid = entry.get("Name"), entry.get("AppID")
        if isinstance(name, str) and isinstance(appid, str) and safe_application_name(name) and PACKAGE_ID.fullmatch(appid):
            result.append(Candidate("", "aumid:" + appid, "Microsoft Store", name))
    return result


def package_registered(target):
    if not is_packaged_target(target) or os.name != "nt":
        return False
    try:
        return any(item.path.casefold() == target.casefold() for item in packaged_candidates())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


class ApplicationScanner:
    def __init__(self, root=None):
        self.lock = threading.Lock()
        self.cache = Path(root) / "applications.json" if root is not None else None
        self.missing = {}  # canonical name -> monotonic time of a full scan that did not find it

    def valid_item(self, item):
        target = item.get("target", "")
        if is_packaged_target(target):
            if item.get("source") != "Microsoft Store" or not safe_application_name(item.get("name", "")):
                return None
            return {**item, "launch_type": "aumid"}
        if Path(target).suffix.casefold() == ".lnk":
            if not local_file(target, (".lnk",)):
                return None
            try:
                target = shortcut_targets([Path(target)]).get(target, "")
            except (OSError, ValueError, subprocess.TimeoutExpired):
                return None
        path = local_file(target)
        if not path or not safe_application_name(path.stem) or not safe_application_name(Path(os.path.realpath(path)).stem) or not safe_application_name(item.get("name", "")):
            return None
        return {**item, "target": str(path), "launch_type": "exe"}

    def valid_items(self):
        items = self.saved()["items"]
        links = [item["target"] for item in items if Path(item["target"]).suffix.casefold() == ".lnk" and local_file(item["target"], (".lnk",))]
        try:
            targets = shortcut_targets([Path(path) for path in links]) if links else {}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            targets = {}
        result = []
        for item in items:
            target = item["target"]
            if Path(target).suffix.casefold() == ".lnk":
                target = targets.get(target, "")
            valid = self.valid_item({**item, "target": target})
            if valid:
                result.append(valid)
        return result

    @staticmethod
    def choice_label(item):
        return (item["name"] + " · " + item["source"] + " · " + Path(item["target"]).parent.name)[:150]

    def find_matches(self, name):
        key = normalized_name(canonical_name(name) or name)
        if not key or not safe_application_name(key):
            return []
        def matching(items):
            result = []
            for item in items:
                names = [item["name"], *item.get("aliases", [])]
                if not any(normalized_name(canonical_name(n) or n) == key for n in names):
                    continue
                valid = self.valid_item(item)
                if valid and (not is_packaged_target(valid["target"]) or package_registered(valid["target"])):
                    result.append(valid)
            if full_name(name) != normalized_name(name):
                exact = [item for item in result if any(full_name(n) == full_name(name) for n in [item["name"], *item.get("aliases", [])])]
                if exact:
                    return exact
            return result
        saved = self.saved()
        found = matching(saved["items"])
        if found:
            return found
        stale_match = any(any(normalized_name(canonical_name(n) or n) == key for n in [item["name"], *item.get("aliases", [])]) for item in saved["items"])
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(saved["scanned_at"])).total_seconds()
        except (ValueError, TypeError):
            age = MISSING_TTL
        if not stale_match and 0 <= age < MISSING_TTL:
            return []
        if time.monotonic() - self.missing.get(key, -MISSING_TTL) < MISSING_TTL:
            return []
        found = matching(self.scan().get("items", []))
        if not found:
            self.missing[key] = time.monotonic()
        return found

    def find(self, name):
        matches = self.find_matches(name)
        return matches[0] if len(matches) == 1 else None

    def suggest_matches(self, name):
        """Phonetic similarity is a proposal only; never authorizes a launch."""
        wanted = sound_key(name)
        if len(wanted) < 3 or len(wanted) > 80 or not safe_application_name(name):
            return []
        ranked = []
        for item in self.valid_items():
            scores = []
            for value in [item["name"], *item.get("aliases", [])]:
                candidate = sound_key(value)
                if len(candidate) >= 3:
                    scores.append(difflib.SequenceMatcher(None, wanted, candidate, autojunk=False).ratio())
                    folded = str.maketrans({"p": "b", "c": "k", "v": "f", "d": "t"})
                    scores.append(difflib.SequenceMatcher(None, wanted.translate(folded), candidate.translate(folded), autojunk=False).ratio())
                    if len(wanted) >= 3 and candidate.translate(folded).startswith(wanted.translate(folded)) and len(candidate) - len(wanted) <= 12:
                        scores.append(.9)
                    # STT often inserts vowels into a spoken acronym ("опыс").
                    # This is only a proposal, and never replaces a confirmation.
                    acronym = re.split(r"\s+", normalized_name(value), maxsplit=1)[0]
                    if re.fullmatch(r"[a-z]{2,5}", acronym) and len(wanted) <= 8:
                        skeleton = lambda text: re.sub(r"[aeiouy]", "", text.translate(folded))
                        a, b = skeleton(wanted), skeleton(acronym)
                        if len(a) >= 2 and a == b:
                            scores.append(.84)
            score = max(scores, default=0)
            if score >= .70:
                ranked.append((score, item))
        ranked.sort(key=lambda row: (-row[0], row[1]["name"].casefold(), row[1]["target"].casefold()))
        return [item for _, item in ranked[:3]]

    def saved(self):
        empty = {"supported": os.name == "nt", "items": [], "categories": CATEGORIES, "warnings": [], "scanned_at": None}
        if not self.cache or not self.cache.is_file():
            return empty
        try:
            if self.cache.stat().st_size > 2_000_000:
                return empty
            data = json.loads(self.cache.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("items"), list) or len(data["items"]) > 4000:
                return empty
            if any(not isinstance(item, dict) or not all(isinstance(item.get(key), str) for key in ("id", "name", "category", "target", "source")) or item["category"] not in CATEGORIES or not isinstance(item.get("aliases"), list) or not all(isinstance(alias, str) for alias in item["aliases"]) for item in data["items"]):
                return empty
            warnings = data.get("warnings", [])
            warnings = [item[:500] for item in warnings[:10] if isinstance(item, str)] if isinstance(warnings, list) else []
            return {**empty, "items": data["items"], "warnings": warnings, "scanned_at": data.get("scanned_at") if isinstance(data.get("scanned_at"), str) else None}
        except (ValueError, OSError):
            return empty

    def scan(self):
        if not self.lock.acquire(blocking=False):
            raise ValueError("Сканирование уже выполняется. Дождитесь завершения.")
        try:
            self.missing.clear()
            previous = {item["id"]: item.get("discovered_at") for item in self.saved()["items"]}
            result = discover()
            result["scanned_at"] = datetime.now(timezone.utc).isoformat()
            for item in result.get("items", []):
                item["discovered_at"] = previous.get(item["id"]) or result["scanned_at"]
            if self.cache and result.get("supported"):
                try:
                    temporary = self.cache.with_suffix(".tmp")
                    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                    temporary.replace(self.cache)
                except OSError:
                    result["warnings"].append("Приложения найдены, но список не удалось сохранить на диск.")
            return result
        finally:
            self.lock.release()
