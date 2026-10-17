# WileyAI — included components

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

Optional engines and model weights are downloaded separately at the user's
request and are governed by their respective licenses. They are not included
in the installer. No user documents, API keys or model weights are bundled.
