"""Bounded streaming guard for degenerate prose; never examines private inputs."""
from collections import Counter
import re


class RepetitionGuard:
    def __init__(self):
        self.tail = ""
        self.checked = 0

    def repetitive(self, delta):
        self.tail = (self.tail + delta)[-12000:]
        self.checked += len(delta)
        if self.checked < 64:
            return False
        self.checked = 0
        # Source code, Markdown tables and quoted passages often repeat by design.
        prose = re.sub(r"```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)", "", self.tail)
        prose = "\n".join(line for line in prose.splitlines() if not re.match(r"\s*(?:[>|]| {4}|\t)", line))
        words = re.findall(r"[^\W_]+", prose.casefold())[-900:]
        if len(words) < 64:
            return False
        # Four identical twelve-word runs also catch the varying sentence endings
        # of a loop, rather than waiting for an entire paragraph to repeat.
        runs = Counter(tuple(words[i:i + 12]) for i in range(len(words) - 11))
        if any(count >= 4 for count in runs.values()):
            return True
        # Short loops ("да, да, да...") have very little information density.
        return len(words) >= 100 and len(set(words[-100:])) <= 5


def history_text(text):
    """Keep an old degenerate answer from teaching the next turn to repeat it."""
    if RepetitionGuard().repetitive(text):
        return text[:240] + "\n[Повторяющаяся часть исключена из контекста.]\n" + text[-240:]
    return text
