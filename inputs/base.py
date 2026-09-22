"""Abstração de dispositivo de entrada.

Todo hardware (micro:bit, Arduino, ESP32, ...) entra no sistema
através de uma subclasse de :class:`InputDevice` que converte o
protocolo próprio em :class:`NormalizedReading`.

O núcleo nunca importa nada daqui; o ``main.py`` drena o adaptador
e alimenta o ``SteeringProcessor`` apenas com dados normalizados.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from core.models import NormalizedReading


class InputDevice(ABC):
    """Interface que todo adaptador de entrada deve implementar."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome legível do adaptador (ex: ``microbit-serial``)."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Inicia leitura em background (thread própria)."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Para a leitura e libera recursos (porta serial, etc)."""
        ...

    @abstractmethod
    def drain(self) -> List[NormalizedReading]:
        """Retorna e remove todas as leituras pendentes (não bloqueia)."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @property
    @abstractmethod
    def port_info(self) -> Optional[str]:
        """Porta/caminho atual ou None se desconectado."""
        ...

    @property
    @abstractmethod
    def last_seen(self) -> Optional[float]:
        """Epoch da última linha válida recebida, ou None."""
        ...
