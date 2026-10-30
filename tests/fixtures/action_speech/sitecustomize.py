"""Only used by the isolated Electron test's child Python process."""
from core import action_dispatch, commands
from core.launch_verification import ExecutionText
from core.voice import Voice


def fake_execute(command, dry_run=False):
    if not dry_run:
        action_dispatch.started()
    text = f"Процесс запущен и подтверждён: {command.label}. PID 30728.\nПроверенный EXE: {command.target}"
    return ExecutionText(text, {"status": "process_started", "pid": 30728, "executable": command.target})


commands.execute = fake_execute


def fake_transcribe(self, data, model, hint="", quality="accurate", environment="normal", vocabulary=()):
    return "Открой Blender"


Voice.transcribe = fake_transcribe
