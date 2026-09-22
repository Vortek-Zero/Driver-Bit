"""Caminhos que funcionam no .exe congelado (PyInstaller) e no fonte.

- ``base_dir()``: código + assets (pasta server/web). No .exe onefile é a
  pasta temporária de extração (``sys._MEIPASS``).
- ``user_dir()``: arquivos editáveis (config.json). No .exe é a pasta
  onde o .exe está (pendrive) — nada é gravado no sistema.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def base_dir() -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if is_frozen() and meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent


def user_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
