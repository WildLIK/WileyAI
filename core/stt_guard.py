"""Conservative transcript checks; no correction, retry or tool execution."""
from collections import Counter
import math
import re


class RecognitionText(str):
    """Keep the existing string contract, with non-sensitive rejection metadata."""
    def __new__(cls, text, reason="", *, characters=None):
        value = super().__new__(cls, text)
        value.reason = reason
        value.characters = len(text) if characters is None else characters
        return value


def assess_transcript(text, prompt, seconds=None):
    value = text.strip()
    words = re.findall(r"\w+", value.casefold())
    known_duration = isinstance(seconds, (int, float)) and math.isfinite(seconds) and seconds > 0
    # Require both temporal implausibility and enough evidence. A short command,
    # a spoken app list or long/repetitive dictation is not rejected by length.
    letters = sum(len(word) for word in words)
    rate = letters / max(.25, seconds) if known_duration else 0
    implausible = letters >= 80 and rate > 45
    grams = Counter(tuple(words[at:at + 3]) for at in range(max(0, len(words) - 2)))
    repetition = sum(count - 1 for count in grams.values()) / max(1, len(words) - 2)
    prompt_words = " ".join(re.findall(r"\w+", prompt.casefold()))
    prompt_copy = len(words) >= 8 and " ".join(words) in prompt_words
    reason = ""
    if len(words) >= 12 and repetition >= .35 and implausible:
        reason = "stt_repetitive_transcript"
    elif prompt_copy and (implausible or not known_duration):
        reason = "stt_prompt_echo"
    elif letters >= 60 and rate > 100:
        reason = "stt_implausible_transcript"
    return RecognitionText("" if reason else value, reason, characters=len(value))
