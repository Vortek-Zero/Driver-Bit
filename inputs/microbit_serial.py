"""Adaptador serial do micro:bit.

Protocolo esperado (uma linha por evento, ``\\n`` terminado)::

    STEER:<graus>     ex: STEER:0, STEER:217, STEER:359
    GEAR:UP
    GEAR:DOWN
    BRAKE:<mm>        ex: BRAKE:34 (ultrassom do freio)
    ACCEL:<mm>        ex: ACCEL:41 (ultrassom do acelerador)
    CLUTCH:<mm>       ex: CLUTCH:28 (ultrassom da embreagem)
    SHIFT:UP / SHIFT:DOWN   (câmbio sequencial, 3ª placa via rádio)
    MODE:AUTO / MODE:MANUAL (botão A do volante alterna)
    HANDBRAKE:ON / HANDBRAKE:OFF (botão B do volante alterna)

Pedais chegam em mm brutos (<=0 = sem eco/invalido); a conversao para
0.0...1.0 e feita no nucleo (core/pedals.py), como o STEER em graus.

Tudo que é específico do micro:bit mora NESTE arquivo.
Para suportar Arduino/ESP32/outro sensor, crie um novo
``InputDevice`` — o núcleo não muda.
"""

from __future__ import annotations

import glob
import logging
import queue
import threading
import time
from typing import List, Optional

from core.models import NormalizedReading

from .base import InputDevice

log = logging.getLogger(__name__)

_LINE_STEER = "STEER:"
_LINE_GEAR = "GEAR:"
_LINE_SHIFT = "SHIFT:"
_LINE_MODE = "MODE:"
_LINE_HANDBRAKE = "HANDBRAKE:"
_LINE_BRAKE = "BRAKE:"
_LINE_ACCEL = "ACCEL:"
_LINE_CLUTCH = "CLUTCH:"
_CANDIDATE_GLOBS = ("/dev/ttyACM*", "/dev/ttyUSB*", "/dev/tty.usbmodem*")


def parse_line(line: str) -> Optional[NormalizedReading]:
    """Converte uma linha serial em leitura normalizada.

    Retorna None para linhas vazias/desconhecidas (com warning de log).
    Levanta ValueError apenas se o prefixo é conhecido mas o valor é
    inválido — o chamador decide se descarta ou derruba a conexão.
    """
    text = line.strip()
    if not text:
        return None
    upper = text.upper()
    if upper.startswith(_LINE_STEER):
        payload = text[len(_LINE_STEER):].strip()
        try:
            deg = float(payload)
        except ValueError as exc:
            raise ValueError(f"STEER inválido: {text!r}") from exc
        return NormalizedReading(heading_deg=deg % 360.0)
    if upper.startswith(_LINE_GEAR):
        payload = upper[len(_LINE_GEAR):].strip()
        if payload in ("UP", "DOWN"):
            return NormalizedReading(gear=payload)  # type: ignore[arg-type]
        raise ValueError(f"GEAR inválido: {text!r}")
    if upper.startswith(_LINE_SHIFT):
        payload = upper[len(_LINE_SHIFT):].strip()
        if payload in ("UP", "DOWN"):
            return NormalizedReading(shift=payload)  # type: ignore[arg-type]
        raise ValueError(f"SHIFT inválido: {text!r}")
    if upper.startswith(_LINE_MODE):
        payload = upper[len(_LINE_MODE):].strip()
        if payload in ("AUTO", "MANUAL"):
            return NormalizedReading(mode=payload)  # type: ignore[arg-type]
        raise ValueError(f"MODE inválido: {text!r}")
    if upper.startswith(_LINE_HANDBRAKE):
        payload = upper[len(_LINE_HANDBRAKE):].strip()
        if payload in ("ON", "OFF"):
            return NormalizedReading(handbrake=(payload == "ON"))
        raise ValueError(f"HANDBRAKE inválido: {text!r}")
    for prefix, field in ((_LINE_BRAKE, "brake_mm"), (_LINE_ACCEL, "accel_mm"),
                          (_LINE_CLUTCH, "clutch_mm")):
        if upper.startswith(prefix):
            payload = text[len(prefix):].strip()
            try:
                mm = float(payload)
            except ValueError as exc:
                raise ValueError(f"{prefix.rstrip(':')} inválido: {text!r}") from exc
            return NormalizedReading(**{field: mm})
    log.debug("linha ignorada: %r", text)
    return None


def find_serial_port(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve ``auto`` para a porta do micro:bit (hub > volante).

    Usa VID/PID USB — nunca pega UART embutida (ttyS*) nem outro
    dispositivo ACM por engano. Retorna None se nada plugado.
    """
    if explicit and explicit != "auto":
        return explicit
    try:
        from .autodetect import detect_setup, pick_port

        return pick_port(detect_setup())
    except Exception:
        pass
    # Fallback sem pyserial: primeiro candidato físico micro:bit-like.
    for pattern in _CANDIDATE_GLOBS:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    return None


class MicrobitSerialInput(InputDevice):
    """Lê o micro:bit via USB-serial em thread própria com auto-reconnect."""

    def __init__(
        self,
        port: str = "auto",
        baudrate: int = 115200,
        read_timeout: float = 1.0,
        reconnect_delay: float = 2.0,
    ) -> None:
        self._configured_port = port
        self._baudrate = baudrate
        self._read_timeout = read_timeout
        self._reconnect_delay = reconnect_delay
        self._queue: queue.Queue[NormalizedReading] = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._connected = False
        self._active_port: Optional[str] = None
        self._last_seen: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "microbit-serial"

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def port_info(self) -> Optional[str]:
        with self._lock:
            return self._active_port

    @property
    def last_seen(self) -> Optional[float]:
        with self._lock:
            return self._last_seen

    def _set_connected(self, value: bool, port: Optional[str]) -> None:
        with self._lock:
            self._connected = value
            self._active_port = port

    def _touch(self) -> None:
        with self._lock:
            self._last_seen = time.time()

    # -- ciclo de vida ------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="microbit-serial", daemon=True
        )
        self._thread.start()
        log.info("adaptador micro:bit iniciado (porta=%s)", self._configured_port)

    def stop(self) -> None:
        self._stop.set()
        self._set_connected(False, None)
        if self._thread:
            self._thread.join(timeout=3.0)

    def drain(self) -> List[NormalizedReading]:
        items: List[NormalizedReading] = []
        try:
            while True:
                items.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        return items

    # -- loop serial ---------------------------------------------------
    def _loop(self) -> None:
        try:
            import serial  # import tardio: permite --simulate sem pyserial
        except ImportError:
            log.error(
                "pyserial não instalado — execute 'pip install -r requirements.txt' "
                "ou rode com --simulate para testar sem hardware."
            )
            return
        while not self._stop.is_set():
            port = find_serial_port(self._configured_port)
            if port is None:
                log.warning(
                    "nenhum micro:bit encontrado no USB; "
                    "conecte a placa (hub ou volante) ou use --simulate"
                )
                self._set_connected(False, None)
                self._stop.wait(self._reconnect_delay)
                continue
            try:
                with serial.Serial(port, self._baudrate, timeout=self._read_timeout) as ser:
                    self._set_connected(True, port)
                    log.info("conectado em %s (%d baud)", port, self._baudrate)
                    # Descarta lixo inicial de reset da placa.
                    ser.reset_input_buffer()
                    while not self._stop.is_set():
                        try:
                            raw = ser.readline()
                        except Exception as exc:
                            log.warning("erro de leitura em %s: %s", port, exc)
                            break
                        if not raw:
                            continue
                        try:
                            text = raw.decode("utf-8", errors="ignore")
                        except Exception:
                            continue
                        try:
                            reading = parse_line(text)
                        except ValueError as exc:
                            log.warning("%s", exc)
                            continue
                        if reading is not None:
                            self._touch()
                            self._queue.put(reading)
            except Exception as exc:
                log.warning("serial %s indisponível: %s", port, exc)
            self._set_connected(False, None)
            if not self._stop.is_set():
                self._stop.wait(self._reconnect_delay)
