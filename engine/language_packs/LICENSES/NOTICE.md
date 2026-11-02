# Additional offline spelling resources (#414)

The seven new spelling dictionaries come from the unmodified `.aff` and `.dic`
files at LibreOffice/dictionaries commit
`4f1df64b2e8e14751aa7c2205d170ca016071315`:
https://github.com/LibreOffice/dictionaries/tree/4f1df64b2e8e14751aa7c2205d170ca016071315

Each language pack preserves its upstream copyright/licence notice and SHA-256
manifest. These are separately licensed data, not Bridge's own dictionary or
newly authored linguistic rules. Complete GPL-2.0, GPL-3.0 and LGPL-2.1 texts are
provided here. Gujarati's upstream notice says GPL without a version; the
original wording is preserved. No version is invented for it.

Spylls 0.1.7 is the unmodified, pure-Python Hunspell implementation installed
from PyPI: https://pypi.org/project/spylls/0.1.7/#files
Source: https://github.com/zverok/spylls
Copyright: Victor Shepelev and the upstream contributors.

Its distributed `LICENSE` is **MPL-2.0**, despite the wheel's MIT classifier.
Bridge uses the actual licence text; a complete MPL-2.0 text is provided here
and PyInstaller preserves the installed distribution metadata/notice. Bridge's
wrapper is separate code and does not modify Spylls.

`MANIFEST.json` records the shared full licence texts and their source/version.
The package and all dictionaries are installed with the application. Runtime
does not contact these sources or download dictionaries.
