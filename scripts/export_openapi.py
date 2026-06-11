# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from solomon.api.app import create_app
from solomon.config import Settings


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="solomon-openapi-") as tmp:
        root = Path(tmp)
        app = create_app(Settings(data_dir=root / "data", journal_dir=root / "journal"))
        destination = Path("docs/api/openapi.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
