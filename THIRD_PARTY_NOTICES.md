# WileyAI — included components

WileyAI Android 0.4.0 includes Vosk Android 0.3.75 (Apache-2.0,
https://github.com/alphacep/vosk-api) and JNA 5.18.1 (dual Apache-2.0 /
LGPL-2.1-or-later; distributed here under Apache-2.0,
https://github.com/java-native-access/jna). The Android APK contains the license
texts in assets/licenses. Its separately downloaded Russian ASR model,
vosk-model-small-ru-0.22, is listed as Apache-2.0 by its publisher:
https://alphacephei.com/vosk/models. No model weights are bundled.
Android TTS engines and their installed voices are separate system components
governed by their respective publishers; WileyAI only requests installed voices
advertised by Android as offline Russian voices.

This distribution includes Electron (MIT), Chromium and its third-party notices
(resources/electron-licenses and LICENSES.chromium.html in the application),
CPython 3.12 (PSF license, runtime/python/LICENSE.txt), python-build-standalone
(https://github.com/astral-sh/python-build-standalone), uv (MIT or Apache-2.0,
https://github.com/astral-sh/uv), React (MIT), Three.js (MIT) and three-vrm (MIT).

Python dependency licenses and metadata are included alongside their packages in
runtime/python/Lib/site-packages/*.dist-info. Source and license texts:
https://github.com/electron/electron, https://github.com/python/cpython,
https://github.com/astral-sh/uv, https://github.com/facebook/react,
https://github.com/mrdoob/three.js, https://github.com/pixiv/three-vrm.

Full license texts for React, React DOM, Three.js and three-vrm are in
resources/licenses. The uv license texts are in resources/runtime/tools.

The mobile pairing QR renderer contains Project Nayuki's QR Code generator
(MIT), https://www.nayuki.io/page/qr-code-generator-library; its full license
and copyright notice are retained in src/vendor/qrcodegen.ts.

Russian spoken-number preparation uses num2words (LGPL-2.1-or-later).
Its source and license are available at https://github.com/savoirfairelinux/num2words;
package license files are included with its Python distribution metadata.

Optional engines and model weights are downloaded separately at the user's
request and are governed by their respective licenses. They are not included
in the installer. No user documents, API keys or AI model weights are bundled.

Optional GigaAM v3 E2E RNN-T speech recognition uses GigaAM (MIT,
https://github.com/salute-developers/GigaAM), the unquantized ONNX exports at
https://huggingface.co/istupakov/gigaam-v3-onnx (MIT), onnx-asr (MIT,
https://github.com/istupakov/onnx-asr), ONNX Runtime (MIT,
https://github.com/microsoft/onnxruntime), and Silero VAD (MIT,
https://github.com/snakers4/silero-vad), exported at
https://huggingface.co/istupakov/silero-vad-onnx. The model and VAD revisions
and file SHA-256 checksums are pinned in core/gigaam.py. Weights are downloaded
separately and do not execute remote Python code.

The Fairy Assistant - Crystal VRM avatar (model version 0.15) is included in
resources/avatars/Fairy_Assistant.vrm. It was authored by the FairyAssistant
project with a locally created VRoid Studio base and original Blender costume,
hair and wing refinements. The embedded VRM 1.0 license and use permissions
apply: https://vrm.dev/licenses/1.0/. Avatar use by everyone and redistribution
are permitted; the remaining permissions are recorded in the VRM metadata.
This is a character asset, separate from optional AI model weights.


Android local chat includes llama.cpp (MIT, copyright the ggml authors), pinned
at 8642541b255bfb5dc39cd351a178be09013a55d6:
https://github.com/ggml-org/llama.cpp/tree/8642541b255bfb5dc39cd351a178be09013a55d6.
The license is included in android/app/src/main/assets/licenses/llama-cpp-MIT.txt.
Qwen3 0.6B model weights (Apache-2.0, https://huggingface.co/Qwen/Qwen3-0.6B)
are downloaded separately from the pinned unsloth GGUF revision recorded in
docs/research/android-llm-catalog.json. No weights are bundled in the APK.

Piper Irina is used through a separately installed upstream sherpa-onnx Android
TTS engine, not linked or bundled with WileyAI. Provenance and APK digest are
recorded in docs/research/android-irina-voice.json. The Irina model card identifies
the dataset license as Unknown; do not infer a model license from the runtime's
license. WileyAI does not redistribute that APK or its voice weights.
