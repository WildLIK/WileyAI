from core.device_audio import music_help
from core.intents import opening_request


def test_explicit_computer_music_commands_are_routed_to_local_tools():
    assert music_help("Включи музыку на компьютере") is not None
    assert opening_request("Включи яндекс музыка") == "открой Яндекс Музыку"
    assert opening_request("Открой блокнот на компьютере") == "Открой блокнот"
    assert opening_request("Не включи яндекс музыка") is None
    assert opening_request('"Открой блокнот на компьютере"') is None
