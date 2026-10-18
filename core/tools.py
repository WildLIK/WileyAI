"""Executable opening tools shared by direct commands, sources and routines."""
from dataclasses import dataclass

from . import commands


@dataclass(frozen=True)
class OpenTool:
    id: str
    kind: str
    name: str
    scope: str
    setting: str


TOOLS = (
    OpenTool("windows.folder.open", "folder", "Открыть папку", "files.open", "allow_file_open"),
    OpenTool("windows.file.open", "file", "Открыть файл", "files.open", "allow_file_open"),
    OpenTool("windows.app.open", "app", "Открыть приложение", "apps.open", "allow_app_open"),
    OpenTool("browser.open", "url", "Открыть сайт", "web.open", "allow_web_open"),
)
ACCESS_FIELDS = ("allow_file_open", "allow_app_open", "allow_web_open", "allow_audio_control")


class OpenTools:
    def __init__(self, store):
        self.store = store

    def catalog(self):
        settings = self.store.settings()
        return [{"id": tool.id, "kind": tool.kind, "name": tool.name, "scope": tool.scope, "enabled": getattr(settings, tool.setting)} for tool in TOOLS]

    def choices(self):
        aliases = self.store.list("aliases", 1000)
        items = [commands.Command(item["kind"], item["target"], item["name"]) for item in aliases]
        items += [commands.Command("folder", target, name) for name, target in commands.folders().items()]
        items += [commands.resolve("запусти " + name, []) for name in commands.APP_NAMES]
        items += [commands.Command("url", target, name) for name, target in commands.SITES.items()]
        result, seen = [], set()
        for item in items:
            key = (item.kind, item.target)
            if key not in seen:
                result.append({"kind": item.kind, "target": item.target, "label": item.label})
                seen.add(key)
        return result

    def validate(self, command):
        tool = next((item for item in TOOLS if item.kind == command.kind), None)
        if tool is None:
            raise ValueError("Неизвестный инструмент открытия")
        if not getattr(self.store.settings(), tool.setting):
            raise ValueError(f"Действие «{tool.name}» отключено. Измените доступ в разделе «Команды».")
        commands.validate(command)
        return tool

    def execute(self, command, dry_run=False):
        try:
            self.validate(command)
            result = commands.execute(command, dry_run=dry_run)
        except Exception as error:
            self.store.audit(command.kind, command.target, "error", {"text": str(error), "label": command.label})
            raise
        evidence = getattr(result, "evidence", None)
        self.store.audit(command.kind, command.target, "preview" if dry_run else evidence["status"] if evidence else "launched", evidence or {"text": str(result), "label": command.label})
        return result
