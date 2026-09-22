"""Adaptador simulado (sem hardware).

Gera um ângulo girando em senoide para testar o dashboard sem o
micro:bit conectado: ``python main.py --simulate``.

Também é um exemplo mínimo de como criar um novo InputDevice.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from typing import List, Optional

from core.models import NormalizedReading

from .base import InputDevice

log = logging.getLogger(__name__)


class SimulatedInput(InputDevice):
    """Senóide de demonstração: gira ±120° em torno de 180°."""

    def __init__(self, period_s: float = 8.0, amplitude_deg: float = 120.0) -> None:
        self._period = period_s
        self._amplitude = amplitude_deg
        self._queue: queue.Queue[NormalizedReading] = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._t0 = time.monotonic()

    @property
    def name(self) -> str:
        return "simulated"

    @property
    def is_connected(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def port_info(self) -> Optional[str]:
        return "simulated"

    @property
    def last_seen(self) -> Optional[float]:
        return time.time() if self.is_connected else None

    def start(self) -> None:
        self._stop.clear()
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="simulated")
        self._thread.start()
        log.info("adaptador simulado iniciado (senoide %.1fs)", self._period)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def drain(self) -> List[NormalizedReading]:
        items: List[NormalizedReading] = []
        try:
            while True:
                items.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        return items

    def _loop(self) -> None:
        while not self._stop.wait(0.05):  # ~20 Hz
            t = time.monotonic() - self._t0
            heading = (180.0 + self._amplitude * math.sin(2 * math.pi * t / self._period)) % 360.0
            self._queue.put(NormalizedReading(heading_deg=heading))
