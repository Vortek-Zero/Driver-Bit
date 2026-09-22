"""Funções puras de ângulo (wrap-around 359° → 0°)."""

from __future__ import annotations

import math
from typing import Iterable


def normalize_compass(deg: float) -> float:
    """Normaliza qualquer ângulo para [0, 360)."""
    return deg % 360.0


def relative_angle(raw_deg: float, center_deg: float) -> float:
    """Diferença assinada raw - center em [-180, +180).

    Convenção: valor positivo = giro horário a partir do centro
    (interpretado como DIREITA), negativo = ESQUERDA.

    Trata corretamente o wrap-around, ex: raw=5, center=355 → +10.
    """
    return (normalize_compass(raw_deg) - normalize_compass(center_deg) + 540.0) % 360.0 - 180.0


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def apply_deadzone(value: float, deadzone: float) -> float:
    """Aplica zona morta com reescala da faixa restante.

    Se |value| < deadzone → 0.0, senão reescala o restante para [0, 1]
    preservando o sinal, de modo que o curso total continua utilizável.
    """
    if deadzone <= 0.0:
        return value
    mag = abs(value)
    if mag < deadzone:
        return 0.0
    return ((mag - deadzone) / (1.0 - deadzone)) * (1.0 if value >= 0 else -1.0)


def circular_mean(degs: Iterable[float]) -> float:
    """Média de ângulos de bússola em [0, 360).

    Média aritmética quebra no wrap (ex: média de 359 e 1 daria 180,
    quando o correto é 0). Aqui cada ângulo vira um vetor unitário e
    o resultado é a direção do vetor soma — imune ao wrap-around.
    """
    xs = 0.0
    ys = 0.0
    n = 0
    for d in degs:
        r = math.radians(normalize_compass(float(d)))
        xs += math.cos(r)
        ys += math.sin(r)
        n += 1
    if n == 0:
        raise ValueError("sem amostras para a média circular")
    if xs == 0.0 and ys == 0.0:
        raise ValueError("amostras opostas se cancelam; segure o volante parado")
    mean = math.degrees(math.atan2(ys, xs)) % 360.0
    # -1e-16 % 360.0 arredonda para exatamente 360.0 em ponto flutuante.
    return 0.0 if mean == 360.0 else mean
