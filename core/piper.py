"""Curated CPU voices. Downloads are pinned and verified before installation."""
from pathlib import Path
import hashlib
import importlib.util
import shutil
import tempfile
import threading

import httpx


REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
VOICES = {
    "irina": ("Ирина · женский", "8ff38212d23da300bbe3705c645e6e5b9475f0bfde01558eb17813e22acaaaaa", "c2ec28bb38e2b59e93b959b3e40348c1afebbd272f30fed5d41205d08e98a9d7", "Лицензия датасета не указана в MODEL_CARD"),
    "denis": ("Денис · мужской", "15fab56e11a097858ee115545d0f697fc2a316c41a291a5362349fb870411b0a", "831c860dac0b5073eaa81610a0a638ec23d90a6cf8e5f871b4485c2cec3767c8", "Датасет CC0; см. MODEL_CARD"),
    "dmitri": ("Дмитрий · мужской", "f073356ebc4bd0f80c5af58df2953a5988bd5bdab1eb38635ce960b071fbefcb", "667ef3117bc642c2892dff7690d8bdc8ca4228aeaa783b2dc1416df632855e0d", "Датасет CC0; см. MODEL_CARD"),
}


def catalog():
    return [{"id": f"piper-{key}", "name": f"Piper · {value[0]}", "kind": "tts", "engine": "piper", "voice": key,
             "description": "Отдельный русский голос. Локальная озвучка на CPU. Сначала установите компонент Piper, затем скачайте голос.",
             "size": "≈ 63 МБ + движок", "languages": "Русский", "license": f"Движок GPL-3.0; {value[3]}",
             "source": f"https://huggingface.co/rhasspy/piper-voices/blob/{REVISION}/ru/ru_RU/{key}/medium/MODEL_CARD"} for key, value in VOICES.items()]


class Piper:
    def __init__(self, root: Path):
        self.root = root / "models" / "piper"
        self.download_lock = threading.Lock()
        self.model = None
        self.selected = ""

    @staticmethod
    def available():
        return importlib.util.find_spec("piper") is not None

    def folder(self, name):
        if name not in VOICES:
            raise ValueError("Выберите голос Piper из каталога")
        return self.root / name

    def installed(self, name):
        folder = self.folder(name)
        return all((folder / f"ru_RU-{name}-medium{suffix}").is_file() for suffix in [".onnx", ".onnx.json"])

    def download(self, name):
        folder = self.folder(name)
        if not self.available():
            raise ValueError("Установите компонент Piper в разделе «Модели → Компоненты» и перезапустите WileyAI")
        with self.download_lock:
            if self.installed(name):
                return
            self.root.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=self.root))
            try:
                base = f"https://huggingface.co/rhasspy/piper-voices/resolve/{REVISION}/ru/ru_RU/{name}/medium"
                for suffix, expected in zip([".onnx", ".onnx.json"], VOICES[name][1:3]):
                    filename = f"ru_RU-{name}-medium{suffix}"
                    digest = hashlib.sha256()
                    size = 0
                    with httpx.stream("GET", f"{base}/{filename}", follow_redirects=True, timeout=180) as response:
                        response.raise_for_status()
                        with (temporary / filename).open("wb") as output:
                            for chunk in response.iter_bytes():
                                size += len(chunk)
                                if size > 70_000_000:
                                    raise ValueError("Файл голоса превышает ожидаемый размер")
                                digest.update(chunk)
                                output.write(chunk)
                    if digest.hexdigest() != expected:
                        raise ValueError("Контрольная сумма голоса не совпала. Повторите загрузку")
                if folder.exists():
                    raise ValueError("Папка голоса неполная: переименуйте её и повторите загрузку")
                temporary.replace(folder)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)

    def load(self, name):
        name = name or "irina"
        if not self.available() or not self.installed(name):
            raise ValueError("Сначала скачайте выбранный голос Piper в разделе «Модели → Озвучка»")
        if self.selected != name:
            from piper import PiperVoice
            self.model = PiperVoice.load(str(self.folder(name) / f"ru_RU-{name}-medium.onnx"), use_cuda=False)
            self.selected = name
        return self.model
