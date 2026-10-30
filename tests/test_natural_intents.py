import pytest

from core.intent_interpreter import interpret
from core.intents import opening_request
from core.commands import opening_target


APPS = ["Blender", "OBS Studio", "RPGReactor", "Firefox", "AIMP", "VS Code", "Telegram", "VLC", "Калькулятор", "Блокнот"]
FORMS = ["Открой {}", "Запусти {}", "Включи {}", "Запускай {}", "Давай откроем {}", "Давай запустим {}", "Уайли, открой {}", "А теперь открой {}", "Можешь запустить {}?", "Пожалуйста, открой {}"]


@pytest.mark.parametrize("app", APPS)
@pytest.mark.parametrize("form", FORMS)
def test_explicit_natural_requests_are_bounded(app, form):
    parsed = interpret(form.format(app))
    assert parsed and parsed.target == app and not parsed.requires_confirmation
    assert opening_target(opening_request(form.format(app))) == app


@pytest.mark.parametrize("app", APPS)
@pytest.mark.parametrize("form", ["Не открывай {}", "Как открыть {}?", "Если я скажу открыть {}", "Он попросил открыть {}", "Расскажи про {}", 'Он сказал: "открой {}"'])
def test_mentions_negation_and_questions_never_become_actions(app, form):
    assert interpret(form.format(app)) is None
    assert opening_request(form.format(app)) is None


@pytest.mark.parametrize("app", APPS)
def test_indirect_need_requires_confirmation(app):
    parsed = interpret("Мне нужен " + app)
    assert parsed and parsed.target == app and parsed.requires_confirmation
    assert opening_request("Мне нужен " + app) is None


@pytest.mark.parametrize("app", APPS)
def test_compound_requests_are_not_silently_reinterpreted(app):
    text = "Открой " + app + " и запусти блокнот"
    assert interpret(text) is None and opening_request(text) is None


def test_phone_target_is_explicitly_distinguished():
    parsed = interpret("Открой Blender на телефоне")
    assert parsed and parsed.device == "phone" and parsed.target == "Blender"
    assert opening_request("Открой Blender на телефоне") is None
