"""Camada de saída genérica (pacote).

Dispositivos de saída (gamepad virtual, teclado virtual, ...) consomem
``WheelState`` do núcleo. Nada aqui conhece micro:bit, serial ou jogos
específicos — o Slow Roads é apenas o primeiro teste.
"""

from .base import OutputDevice

__all__ = ["OutputDevice"]
