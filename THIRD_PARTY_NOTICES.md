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

Optional ASR, TTS, language-model and Smart Turn weights are downloaded separately
at the user's request and are governed by their respective licenses. User
documents and API keys are never bundled. The small Silero VAD model below is
included for local speech endpoint detection.

WileyAI Android 0.13.6b-c9 and later may optionally use the GigaAM v3 RNN-T
model (MIT, copyright 2024 GigaChat Team,
https://github.com/salute-developers/GigaAM) as an experimental offline Russian
speech recognizer. The model is never bundled: the user downloads the pinned
sherpa-onnx ONNX export
(csukuangfj/sherpa-onnx-nemo-transducer-giga-am-v3-russian-2025-12-16 on
Hugging Face) at their explicit request, and each file is verified against its
published SHA-256 before installation. The APK includes the pinned sherpa-onnx
1.13.5 runtime when the reviewed AAR is available (Apache-2.0,
https://github.com/k2-fsa/sherpa-onnx), with Kotlin stdlib 1.9.24 (Apache-2.0,
https://github.com/JetBrains/kotlin). ONNX Runtime MIT and third-party notices
are included in assets/voice-vad. These libraries do not include GigaAM weights.

Desktop speech endpoint detection includes ONNX Runtime Web 1.31.1 (MIT,
https://github.com/microsoft/onnxruntime) and Silero VAD v5 (MIT, copyright
2020-present Silero Team, https://github.com/snakers4/silero-vad). The ONNX
artifact comes from ricky0123/vad revision
2e5aca93e3902f04ff5b7eb4a9633926cdca9cf6, file silero_vad_v5.onnx, SHA-256
2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f.
The vad-web microphone wrapper is not included; WileyAI retains its own
AudioWorklet and uses a dedicated local inference worker. TEN VAD and WebRTC VAD
were evaluated locally and are not included in the application.
Android uses the same Silero v5 artifact through sherpa-onnx to detect speech
within GigaAM command sessions after voice activation.

Silero VAD model license:

Copyright (c) 2020-present Silero Team

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Optional Smart Turn v3.2 CPU weights and code are BSD-2-Clause, copyright
2024–2025 Daily, https://github.com/pipecat-ai/smart-turn. WileyAI downloads the
pinned ONNX artifact only after an explicit request, verifies its SHA-256 and
does not execute Python from the model repository. The original code and model
license is included in resources/licenses/voice/Smart-Turn-LICENSE.txt.

Optional GigaAM v3 E2E RNN-T speech recognition uses GigaAM (MIT,
https://github.com/salute-developers/GigaAM), the unquantized ONNX exports at
https://huggingface.co/istupakov/gigaam-v3-onnx (MIT), onnx-asr (MIT,
https://github.com/istupakov/onnx-asr), ONNX Runtime (MIT,
https://github.com/microsoft/onnxruntime), and Silero VAD (MIT,
https://github.com/snakers4/silero-vad), exported at
https://huggingface.co/istupakov/silero-vad-onnx. The model and VAD revisions
and file SHA-256 checksums are pinned in core/gigaam.py. Weights are downloaded
separately and do not execute remote Python code.

The Fairy Assistant - Crystal VRM avatar (model version 0.16) is included in
resources/avatars/Fairy_Assistant.vrm. It was authored by the FairyAssistant
project with a locally created VRoid Studio base and original Blender costume,
hair and wing refinements. The embedded VRM 1.0 license and use permissions
apply: https://vrm.dev/licenses/1.0/. Its metadata permits redistribution and
personal non-profit use, requires credit to FairyAssistant project, and
prohibits modification. The VRM is distributed as-is.
This is a character asset, separate from optional AI model weights.


Android local chat includes llama.cpp (MIT, copyright the ggml authors), pinned
at 8642541b255bfb5dc39cd351a178be09013a55d6:
https://github.com/ggml-org/llama.cpp/tree/8642541b255bfb5dc39cd351a178be09013a55d6.
The license is included in android/app/src/main/assets/licenses/llama-cpp-MIT.txt.
Qwen3 0.6B model weights (Apache-2.0, https://huggingface.co/Qwen/Qwen3-0.6B)
are downloaded separately from the pinned unsloth GGUF revision recorded in
docs/research/android-llm-catalog.json.

The public builds ship the verified Silero VAD v5 artifact above. Android
also includes the Apache-2.0 3D-Speaker CAM++ voice profile model
(`iic/speech_campplus_sv_zh_en_16k-common_advanced`, ModelScope) as an ONNX
export distributed by sherpa-onnx. The exact size and SHA-256 are pinned in
`scripts/prepare-android-camplus.py`. See https://github.com/modelscope/3D-Speaker
and https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models.
The Android APK includes the Apache-2.0 license. Locally trained wake-word
models and research recordings are excluded.

Piper Irina is used through a separately installed upstream sherpa-onnx Android
TTS engine, not linked or bundled with WileyAI. Provenance and APK digest are
recorded in docs/research/android-irina-voice.json. The Irina model card identifies
the dataset license as Unknown; do not infer a model license from the runtime's
license. WileyAI does not redistribute that APK or its voice weights.
