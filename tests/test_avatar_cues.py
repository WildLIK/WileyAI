import pytest

from core.avatar_cues import AvatarCue
from core.config import Settings
from core.persona import prompt


@pytest.mark.parametrize("size", [1, 5, 1000])
def test_cue_is_hidden_and_validated_across_arbitrary_chunk_boundaries(size):
    parser = AvatarCue(True)
    response = "  [[avatar:surprised:nod]]\nТакого поворота событий я не ожидала."
    rendered, cues = "", []
    for i in range(0, len(response), size):
        text, cue = parser.feed(response[i:i + size])
        rendered += text
        if cue:
            cues.append(cue)
    rendered += parser.finish()
    assert rendered.lstrip() == "Такого поворота событий я не ожидала."
    assert cues == [{"emotion": "surprised", "gesture": "nod"}]


def test_unknown_actions_never_become_cues_and_normal_text_is_preserved():
    parser = AvatarCue(True)
    text, cue = parser.feed("[[avatar:happy:delete]]\nОбычный текст.")
    assert text == "Обычный текст." and cue is None
    parser = AvatarCue(True)
    assert parser.feed("Пример [[avatar:happy:nod]] внутри цитаты.") == ("Пример [[avatar:happy:nod]] внутри цитаты.", None)
    parser = AvatarCue(True)
    assert parser.feed("[[avatar:") == ("", None)
    assert parser.finish() == ""


def test_semantic_presentation_metadata_is_optional_and_needs_no_extra_model_call():
    assert "[[avatar:" not in prompt(Settings())
    assert "[[avatar:" in prompt(Settings(avatar_path="fairy.vrm"))
    assert "[[avatar:" not in prompt(Settings(avatar_path="fairy.vrm", avatar_expressions=False))
