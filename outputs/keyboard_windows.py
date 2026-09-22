"""Saída genérica: teclado virtual no Windows (sem driver, sem admin).

Usa ``SendInput`` via ``ctypes`` (só stdlib): funciona em máquina
escolar bloqueada, sem instalar nada.

Como teclado é digital, direção e pedais usam PWM (~10 Hz): a fração do
tempo com a tecla pressionada é proporcional ao valor analógico, o que
preserva a sensação progressiva do volante/pedais. Botões de marcha
seguram a tecla enquanto o evento está ativo.

Nada aqui conhece micro:bit, serial ou jogos — consome ``WheelState``.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.models import WheelState

from .base import OutputDevice

log = logging.getLogger(__name__)

# -- mapa nome → (código VK, tecla estendida?) ---------------------------
_EXTENDED = {"left", "right", "up", "down"}

_VK: Dict[str, Tuple[int, bool]] = {
    "left": (0x25, True),
    "right": (0x27, True),
    "up": (0x26, True),
    "down": (0x28, True),
    "space": (0x20, False),
    "enter": (0x0D, False),
    "esc": (0x1B, False),
    "tab": (0x09, False),
    "shift": (0x10, False),
    "ctrl": (0x11, False),
    "alt": (0x12, False),
}
_VK.update({c: (ord(c.upper()), False) for c in "abcdefghijklmnopqrstuvwxyz0123456789"})
_VK.update({f"f{i}": (0x6F + i, False) for i in range(1, 13)})


def parse_key(name: str) -> Tuple[int, bool]:
    """``"left"`` → ``(0x25, True)``. Levanta ValueError se desconhecida."""
    key = name.strip().lower()
    if key not in _VK:
        raise ValueError(
            f"tecla desconhecida: {name!r} "
            f"(use: {', '.join(sorted(_VK))})"
        )
    return _VK[key]


@dataclass
class KeyMap:
    """Teclas de destino (nomes de :func:`parse_key`)."""

    left: str = "left"
    right: str = "right"
    accel: str = "up"
    brake: str = "down"
    gear_up: str = "shift"  # legado (firmware antigo)
    gear_down: str = "space"  # legado (firmware antigo)
    shift_up: str = "e"  # câmbio sequencial sobe
    shift_down: str = "q"  # câmbio sequencial desce
    handbrake: str = "space"  # freio de mão (botão B do volante)

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "KeyMap":
        data = data or {}
        known = {f.name for f in cls.__dataclass_fields__.values()}
        valid: dict = {}
        for name in known & set(data):
            parse_key(str(data[name]))  # valida já
            valid[name] = str(data[name])
        return cls(**valid)  # desconhecidas = ignoradas (compat)


class KeyPwm:
    """PWM por tecla: fração de ticks pressionada ~= valor analógico."""

    def __init__(self, steps: int = 6, threshold: float = 0.08) -> None:
        self._steps = steps
        self._threshold = threshold
        self._counter = 0

    def update(self, value01: float) -> bool:
        """Chamar a cada tick da bomba (~60 Hz). Retorna tecla pressionada/solta."""
        v = max(0.0, min(1.0, float(value01)))
        downs = 0 if v < self._threshold else round(v * self._steps)
        down = self._counter < downs
        self._counter = (self._counter + 1) % self._steps
        return down


class KeyboardWindows(OutputDevice):
    """Teclado virtual (Windows). Publica snapshots como teclas."""

    def __init__(self, keymap: Optional[KeyMap] = None) -> None:
        self._keymap = keymap or KeyMap()
        self._codes: Dict[str, Tuple[int, bool]] = {}
        self._down: Dict[str, bool] = {}
        self._steer_l = KeyPwm()
        self._steer_r = KeyPwm()
        self._accel = KeyPwm()
        self._brake = KeyPwm()
        self._send = None  # (vk, extended, down) -> None

    @property
    def name(self) -> str:
        return "keyboard-windows"

    def start(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError(
                "saída keyboard-windows só funciona no Windows "
                "(no Linux use --gamepad)"
            )
        import ctypes
        from ctypes import wintypes

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.ULONG_PTR),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("ki", KEYBDINPUT)]

        send_input = ctypes.windll.user32.SendInput
        KEYEVENTF_KEYUP = 0x0002
        KEYEVENTF_EXTENDED = 0x0001

        def _send(vk: int, extended: bool, down: bool) -> None:
            flags = 0 if down else KEYEVENTF_KEYUP
            if extended:
                flags |= KEYEVENTF_EXTENDED
            inp = INPUT(
                type=1, ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
            )
            if send_input(1, ctypes.byref(inp), ctypes.sizeof(inp)) != 1:
                raise OSError("SendInput falhou")

        self._send = _send
        for attr in ("left", "right", "accel", "brake", "gear_up", "gear_down",
                     "shift_up", "shift_down", "handbrake"):
            key_name = getattr(self._keymap, attr)
            self._codes[attr] = parse_key(key_name)
            self._down[attr] = False
        log.info("teclado virtual ativo (mapa: %s)", self._keymap)

    def _set(self, attr: str, down: bool) -> None:
        """Só envia na transição (evita repetir tecla pressionada)."""
        assert self._send is not None
        if down == self._down[attr]:
            return
        vk, extended = self._codes[attr]
        try:
            self._send(vk, extended, down)
        except OSError as exc:
            log.warning("tecla %s: %s", attr, exc)
            return
        self._down[attr] = down

    def stop(self) -> None:
        if self._send is None:
            return
        for attr, is_down in list(self._down.items()):
            if is_down:
                self._set(attr, False)
        self._send = None

    def publish(self, state: WheelState) -> None:
        if self._send is None:
            raise RuntimeError("teclado não iniciado (chame start() primeiro)")
        steering = max(-1.0, min(1.0, state.steering))
        self._set("left", self._steer_l.update(-steering))
        self._set("right", self._steer_r.update(steering))
        self._set("accel", self._accel.update(state.accel))
        self._set("brake", self._brake.update(state.brake))
        self._set("gear_up", bool(state.gear_up))
        self._set("gear_down", bool(state.gear_down))
        self._set("shift_up", bool(state.shift_up))
        self._set("shift_down", bool(state.shift_down))
        self._set("handbrake", bool(state.handbrake))


def available_keys() -> List[str]:
    return sorted(_VK)
