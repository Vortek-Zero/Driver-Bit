"""Pedais (freio/acelerador) a partir de distância em milímetros.

Quanto mais perto do sensor, mais pisado: ``near_mm`` (ou menos) é fundo
(1.0), ``far_mm`` (ou mais) é solto (0.0), linear entre eles.

Leitura ``<= 0`` significa SEM ECO (mão longe demais OU colada no ponto
cego) — é inválida, nunca posição. Inválida congela o valor por
``hold_ms`` (cobre flicker) e depois decai para solto (segurança: mão
retirada não pode ficar acelerando).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from .angles import clamp


@dataclass
class PedalConfig:
    """Parâmetros de um pedal (iguais p/ freio e acel por padrão)."""

    far_mm: float = 50.0  # >= isto = solto (0.0)
    near_mm: float = 20.0  # <= isto = fundo (1.0)
    smoothing: float = 0.5  # alpha do EMA em (0, 1]; 1.0 = sem suavização
    hold_ms: int = 250  # congela em leitura inválida antes de soltar

    def validate(self) -> None:
        if not 1.0 <= self.near_mm < self.far_mm <= 500.0:
            raise ValueError("pedal exige 1 <= near_mm < far_mm <= 500")
        if not 0.0 < self.smoothing <= 1.0:
            raise ValueError("pedal smoothing deve estar em (0, 1]")
        if self.hold_ms < 0:
            raise ValueError("pedal hold_ms deve ser >= 0")


Clock = Callable[[], float]


class PedalChannel:
    """Um pedal: mm bruto → 0.0 (solto) … 1.0 (fundo)."""

    def __init__(self, config: Optional[PedalConfig] = None,
                 clock: Clock = time.monotonic) -> None:
        self._config = config or PedalConfig()
        self._config.validate()
        self._clock = clock
        self._value: float = 0.0
        self._last_valid_at: float = 0.0
        self._has_valid: bool = False

    def update(self, mm: Optional[float]) -> float:
        """Processa uma leitura (None = sem linha neste ciclo, mantém)."""
        if mm is None:
            return self._value
        now = self._clock()
        if mm > 0:
            span = self._config.far_mm - self._config.near_mm
            target = (self._config.far_mm - mm) / span
            target = clamp(target, 0.0, 1.0)
            self._last_valid_at = now
            self._has_valid = True
        elif not self._has_valid:
            target = 0.0
        elif (now - self._last_valid_at) * 1000.0 <= self._config.hold_ms:
            target = self._value  # congela: flicker de eco perdido
        else:
            target = 0.0  # mão retirada: solta por segurança
        alpha = self._config.smoothing
        self._value = clamp(alpha * target + (1.0 - alpha) * self._value, 0.0, 1.0)
        return self._value

    @property
    def value(self) -> float:
        return self._value
