"""Saída genérica: gamepad virtual Linux via uinput.

Expõe o ``WheelState`` como um controle estilo Xbox 360
(``ABS_X`` analógico + botões), visível para qualquer aplicação que leia
gamepads — navegadores (Gamepad API), jogos nativos, Steam, etc.

Mapeamento (fixo e documentado):

- ``steering`` (-1.0 esq … +1.0 dir) → eixo ``ABS_X`` (-32767 … +32767)
- ``brake`` (0.0 … 1.0) → gatilho ``ABS_Z`` (0 … 255, estilo LT)
- ``accel`` (0.0 … 1.0) → gatilho ``ABS_RZ`` (0 … 255, estilo RT)
- ``clutch`` (0.0 … 1.0) → ``ABS_THROTTLE`` (0 … 255, extra p/ mapeamento)
- ``gear_down`` (A, firmware antigo) → ``BTN_SOUTH`` (botão A do pad)
- ``handbrake`` (B do volante) e ``gear_up`` (B, firmware antigo,
  mesmo botão físico) → ``BTN_EAST`` (botão B do pad)
- ``shift_down`` (câmbio) → ``BTN_TL`` (LB, borboleta esq.)
- ``shift_up`` (câmbio) → ``BTN_TR`` (RB, borboleta dir.)

Os demais eixos/botões do perfil Xbox 360 existem centrados/soltos
apenas para detecção de layout padrão pelos navegadores.

Dependências Linux (verificadas em :func:`check_gamepad_requirements`):

- pacote ``python-evdev`` (já instalado neste ambiente);
- módulo ``uinput`` carregado (``/dev/uinput`` presente);
- permissão de escrita em ``/dev/uinput`` (grupo ``input``).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

from core.models import WheelState

from .base import OutputDevice

log = logging.getLogger(__name__)

DEVICE_NAME = "WheelBridge Virtual Wheel"
VENDOR_ID = 0x045E  # perfil compatível Xbox 360 (mapeamento padrão)
PRODUCT_ID = 0x028E
ABS_MAX = 32767


def steering_to_abs(value: float, abs_max: int = ABS_MAX) -> int:
    """Converte steering -1.0…+1.0 em valor de eixo (com saturação)."""
    clamped = max(-1.0, min(1.0, float(value)))
    return int(round(clamped * abs_max))


def pedal_to_trigger(value: float) -> int:
    """Converte pedal 0.0…1.0 em valor de gatilho 0…255 (com saturação)."""
    clamped = max(0.0, min(1.0, float(value)))
    return int(round(clamped * 255))


def check_gamepad_requirements() -> List[str]:
    """Retorna lista de problemas (vazia = pronto). Cada item já diz o fix."""
    problems: List[str] = []
    try:
        from evdev import UInput  # noqa: F401
    except ImportError:
        problems.append(
            "biblioteca python-evdev ausente — instale com: "
            "sudo pacman -S python-evdev   (ou: pip install evdev)"
        )
        return problems  # sem evdev, nada mais adianta checar
    if not os.path.exists("/dev/uinput"):
        problems.append(
            "/dev/uinput não existe (módulo uinput descarregado) — ative com: "
            "sudo modprobe uinput   e persista com: "
            "echo uinput | sudo tee /etc/modules-load.d/uinput.conf"
        )
    elif not os.access("/dev/uinput", os.W_OK):
        problems.append(
            "sem escrita em /dev/uinput — libere com: "
            "sudo usermod -aG input $USER   (depois faça logout/login)  "
            "ou regra udev: echo 'KERNEL==\"uinput\", GROUP=\"input\", MODE=\"0660\"' "
            "| sudo tee /etc/udev/rules.d/99-uinput.rules && sudo udevadm control --reload"
        )
    return problems


def _build_capabilities(ecodes: Any, AbsInfo: Any) -> Dict[Any, Any]:
    # AbsInfo(value, min, max, fuzz, flat, resolution)
    axis = lambda: AbsInfo(0, -ABS_MAX, ABS_MAX, 16, 0, 0)
    abs_x = (ecodes.ABS_X, axis())
    abs_y = (ecodes.ABS_Y, axis())
    abs_rx = (ecodes.ABS_RX, axis())
    abs_ry = (ecodes.ABS_RY, axis())
    abs_z = (ecodes.ABS_Z, AbsInfo(0, 0, 255, 0, 0, 0))
    abs_rz = (ecodes.ABS_RZ, AbsInfo(0, 0, 255, 0, 0, 0))
    abs_throttle = (ecodes.ABS_THROTTLE, AbsInfo(0, 0, 255, 0, 0, 0))
    buttons = [
        ecodes.BTN_SOUTH,  # A = GEAR:DOWN
        ecodes.BTN_EAST,  # B = GEAR:UP
        ecodes.BTN_NORTH,
        ecodes.BTN_WEST,
        ecodes.BTN_TL,
        ecodes.BTN_TR,
        ecodes.BTN_SELECT,
        ecodes.BTN_START,
        ecodes.BTN_MODE,
        ecodes.BTN_THUMBL,
        ecodes.BTN_THUMBR,
    ]
    return {ecodes.EV_ABS: [abs_x, abs_y, abs_rx, abs_ry, abs_z, abs_rz,
                            abs_throttle],
            ecodes.EV_KEY: buttons}


class UinputGamepad(OutputDevice):
    """Gamepad virtual via uinput; publica snapshots do núcleo."""

    def __init__(
        self,
        device_name: str = DEVICE_NAME,
        ui_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        """
        Args:
            device_name: nome exibido em /dev/input e na Gamepad API.
            ui_factory: injeção para testes (recebe os mesmos kwargs do
                ``evdev.UInput`` e retorna objeto com ``write()``/``syn()``).
        """
        self._device_name = device_name
        self._ui_factory = ui_factory
        self._ui: Optional[Any] = None
        self._ecodes: Optional[Any] = None
        self._btn_up = False
        self._btn_down = False
        self._shift_up = False
        self._shift_down = False

    @property
    def name(self) -> str:
        return "uinput-gamepad"

    @property
    def device_path(self) -> Optional[str]:
        """Caminho /dev/input/eventX do pad virtual (None se inativo)."""
        if self._ui is None:
            return None
        try:
            return self._ui.device.path  # type: ignore[no-any-return]
        except AttributeError:
            return None

    def start(self) -> None:
        problems = check_gamepad_requirements()
        if problems and self._ui_factory is None:
            raise RuntimeError("gamepad indisponível:\n- " + "\n- ".join(problems))
        from evdev import AbsInfo, UInput, ecodes

        self._ecodes = ecodes
        capabilities = _build_capabilities(ecodes, AbsInfo)
        factory = self._ui_factory or UInput
        self._ui = factory(
            events=capabilities,
            name=self._device_name,
            vendor=VENDOR_ID,
            product=PRODUCT_ID,
            version=0x110,
        )
        # Estado neutro inicial: eixo centrado, botões soltos.
        self._write_axis(0)
        self._write_buttons(False, False)
        self._write_shift(False, False)
        if self._ui is not None:
            self._ui.syn()
        log.info("gamepad virtual '%s' ativo (%s)", self._device_name, self.device_path)

    def stop(self) -> None:
        ui, self._ui = self._ui, None
        if ui is not None:
            try:
                # Solta tudo antes de destruir (evita botão "preso" no jogo).
                self._ecodes_cache_write(ui, 0, False, False)
                if self._ecodes is not None:
                    ui.write(self._ecodes.EV_KEY, self._ecodes.BTN_TR, 0)
                    ui.write(self._ecodes.EV_KEY, self._ecodes.BTN_TL, 0)
                ui.syn()
            except Exception:
                pass
            try:
                ui.close()
            except Exception:
                pass

    def _ecodes_cache_write(self, ui: Any, axis: int, up: bool, down: bool) -> None:
        ecodes = self._ecodes
        ui.write(ecodes.EV_ABS, ecodes.ABS_X, axis)
        ui.write(ecodes.EV_KEY, ecodes.BTN_EAST, 1 if up else 0)
        ui.write(ecodes.EV_KEY, ecodes.BTN_SOUTH, 1 if down else 0)

    def _write_axis(self, value: int) -> None:
        assert self._ui is not None and self._ecodes is not None
        self._ui.write(self._ecodes.EV_ABS, self._ecodes.ABS_X, value)

    def _write_buttons(self, up: bool, down: bool) -> None:
        assert self._ui is not None and self._ecodes is not None
        if up != self._btn_up:
            self._ui.write(self._ecodes.EV_KEY, self._ecodes.BTN_EAST, 1 if up else 0)
            self._btn_up = up
        if down != self._btn_down:
            self._ui.write(self._ecodes.EV_KEY, self._ecodes.BTN_SOUTH, 1 if down else 0)
            self._btn_down = down

    def _write_shift(self, up: bool, down: bool) -> None:
        assert self._ui is not None and self._ecodes is not None
        if up != self._shift_up:
            self._ui.write(self._ecodes.EV_KEY, self._ecodes.BTN_TR, 1 if up else 0)
            self._shift_up = up
        if down != self._shift_down:
            self._ui.write(self._ecodes.EV_KEY, self._ecodes.BTN_TL, 1 if down else 0)
            self._shift_down = down

    def publish(self, state: WheelState) -> None:
        """Eixo/gatilhos a cada chamada; botões só na transição (edge)."""
        if self._ui is None or self._ecodes is None:
            raise RuntimeError("gamepad não iniciado (chame start() primeiro)")
        self._write_axis(steering_to_abs(state.steering))
        self._ui.write(self._ecodes.EV_ABS, self._ecodes.ABS_Z, pedal_to_trigger(state.brake))
        self._ui.write(self._ecodes.EV_ABS, self._ecodes.ABS_RZ, pedal_to_trigger(state.accel))
        self._ui.write(self._ecodes.EV_ABS, self._ecodes.ABS_THROTTLE,
                       pedal_to_trigger(state.clutch))
        self._write_buttons(state.gear_up, state.gear_down)
        self._write_shift(state.shift_up, state.shift_down)
        # B do volante = freio de mão (firmware novo) ou GEAR:UP (antigo:
        # mesmo botão físico, mesmo botão do pad).
        self._write_buttons(state.handbrake or state.gear_up, state.gear_down)
        self._ui.syn()
