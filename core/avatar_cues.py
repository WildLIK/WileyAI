"""Optional bounded presentation metadata from the model, never executable actions."""
import re

EMOTIONS = {"neutral", "happy", "sad", "angry", "relaxed", "surprised"}
GESTURES = {"none", "nod", "wave", "comfort", "joy", "cute", "surprise", "explain", "think", "praise", "point", "listen", "thumbsup", "shy", "tired"}
STOP_MARKER = "[Генерация остановлена из-за повторов.]"


class AvatarCue:
    def __init__(self, enabled):
        self.pending = ""
        self.done = not enabled

    def feed(self, text):
        if self.done:
            return text, None
        self.pending += text
        value = self.pending.lstrip()
        prefix = "[[avatar:"
        if len(value) <= len(prefix) and prefix.startswith(value):
            return "", None
        if value.startswith(prefix) and "]]" not in value and len(value) < 100:
            return "", None
        self.done = True
        match = re.match(r"\[\[avatar:([a-z]+):([a-z]+)\]\][ \t]*\r?\n?", value)
        if match:
            emotion, gesture = match[1], match[2]
            self.pending = ""
            cue = {"emotion": emotion, "gesture": gesture} if emotion in EMOTIONS and gesture in GESTURES else None
            return value[match.end():], cue
        result, self.pending = self.pending, ""
        return result, None

    def finish(self):
        text, self.pending = self.pending, ""
        return "" if text.lstrip().startswith("[[avatar:") else text
