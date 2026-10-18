"""Bounded, read-only Windows app discovery. Scanning never launches anything."""
from dataclasses import dataclass
import glob
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import threading
import time

from .app_catalog import CATALOG, CATEGORIES, shortcut_spec


@dataclass
class Candidate:
    spec_id: str
    path: str
    source: str


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
        return path if path.is_file() else None
    except (OSError, ValueError):
        return None


def registry_candidates():
    import winreg
    results = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for spec in CATALOG:
                for exe in spec.executables:
                    try:
                        key = r"Software\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + exe
                        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as opened:
                            value, kind = winreg.QueryValueEx(opened, None)
                        if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                            results.append(Candidate(spec.id, value, "Регистрация Windows"))
                    except OSError:
                        pass
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
                        spec = shortcut_spec(path.stem)
                        if spec:
                            found.append((spec, path))
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
    candidates, warnings = registry_candidates(), []
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
    # A valid shortcut preserves the application's arguments/working directory.
    linked = [Candidate(spec.id, str(path), "Ярлык меню «Пуск»") for spec, path in links if local_file(targets.get(str(path)))]
    items, seen = [], set()
    known = {spec.id: spec for spec in CATALOG}
    for item in [*linked, *candidates]:
        if item.spec_id in seen or item.spec_id not in known:
            continue
        path = local_file(item.path, (".exe", ".lnk"))
        if path is None:
            continue
        spec = known[item.spec_id]
        seen.add(spec.id)
        items.append({"id": hashlib.sha256((spec.id + str(path).casefold()).encode()).hexdigest()[:24],
                      "name": spec.name, "category": spec.category, "target": str(path),
                      "source": item.source, "aliases": spec.aliases})
    order = list(CATEGORIES)
    items.sort(key=lambda item: (order.index(item["category"]), item["name"].casefold()))
    return {"supported": True, "items": items, "categories": CATEGORIES, "warnings": warnings}


class ApplicationScanner:
    def __init__(self):
        self.lock = threading.Lock()

    def scan(self):
        if not self.lock.acquire(blocking=False):
            raise ValueError("Сканирование уже выполняется. Дождитесь завершения.")
        try:
            return discover()
        finally:
            self.lock.release()
