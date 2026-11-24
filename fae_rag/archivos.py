"""Persistencia local de resultados JSON."""

import json
from pathlib import Path
from typing import Any


def guardar_json(path: Path, value: Any) -> None:
    """Guardar un resultado local usando UTF-8 y una estructura legible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
