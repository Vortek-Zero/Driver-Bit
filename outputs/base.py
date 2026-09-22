"""Abstração de dispositivo de saída.

Toda saída (gamepad virtual Linux, futuramente teclado virtual, rede,
...) implementa :class:`OutputDevice` consumindo apenas ``WheelState``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import WheelState


class OutputDevice(ABC):
    """Interface que toda saída genérica deve implementar."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome legível da saída (ex: ``uinput-gamepad``)."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Cria/ativa o dispositivo de saída."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Desativa o dispositivo e libera recursos."""
        ...

    @abstractmethod
    def publish(self, state: WheelState) -> None:
        """Publica um snapshot do núcleo no dispositivo de saída."""
        ...
