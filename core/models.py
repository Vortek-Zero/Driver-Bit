"""Modelos de dados normalizados do núcleo.

O núcleo trabalha SOMENTE com estes tipos. Nenhum nome de
hardware (micro:bit, Arduino, ESP32, serial, ...) pode aparecer aqui.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

GearButton = Literal["UP", "DOWN"]
DriveMode = Literal["AUTO", "MANUAL"]


@dataclass(frozen=True)
class NormalizedReading:
    """Um evento já convertido pelo InputAdapter.

    O adaptador converte o protocolo bruto do dispositivo
    (ex: ``STEER:217``) para este formato neutro.

    Attributes:
        heading_deg: ângulo bruto da bússola em [0, 360), ou None se
            esta leitura não carrega ângulo (ex: evento puro de botão).
        gear: ``"UP"`` / ``"DOWN"`` quando um botão de marcha foi
            pressionado, ou None caso contrário.
        shift: ``"UP"`` / ``"DOWN"`` do câmbio sequencial (3ª placa),
            ou None caso contrário.
        brake_mm: distância do pedal de freio em milímetros
            (<=0 = leitura inválida/sem eco), ou None se esta linha
            não carrega pedal.
        accel_mm: idem, acelerador.
        clutch_mm: idem, embreagem.
    """

    heading_deg: Optional[float] = None
    gear: Optional[GearButton] = None
    shift: Optional[GearButton] = None
    mode: Optional[DriveMode] = None
    handbrake: Optional[bool] = None
    brake_mm: Optional[float] = None
    accel_mm: Optional[float] = None
    clutch_mm: Optional[float] = None


@dataclass
class WheelState:
    """Estado atual do volante, calculado pelo SteeringProcessor."""

    raw_angle: Optional[float] = None
    center: Optional[float] = None
    relative_angle: Optional[float] = None
    steering: float = 0.0  # -1.0 (esquerda) .. +1.0 (direita)
    brake: float = 0.0  # 0.0 (solto) .. 1.0 (fundo)
    accel: float = 0.0  # 0.0 (solto) .. 1.0 (fundo)
    clutch: float = 0.0  # 0.0 (solto) .. 1.0 (fundo)
    auto_mode: bool = False  # True = câmbio automático (SHIFT ignorado)
    handbrake: bool = False  # freio de mão (botão B do volante)
    gear_up: bool = False
    gear_down: bool = False
    gear_up_count: int = 0
    gear_down_count: int = 0
    shift_up: bool = False
    shift_down: bool = False
    shift_up_count: int = 0
    shift_down_count: int = 0
    connected: bool = False
    port: Optional[str] = None
    last_seen: Optional[float] = None  # epoch seconds

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProcessorConfig:
    """Parâmetros ajustáveis do processamento (sem hardcode no núcleo)."""

    max_angle_deg: float = 90.0  # ângulo p/ atingir |steering| == 1.0
    deadzone: float = 0.05  # 0.0 .. <1.0, fração do curso
    smoothing: float = 0.35  # alpha do EMA em (0, 1]; 1.0 = sem suavização
    gear_flash_ms: int = 400  # quanto tempo o botão fica "aceso" no dashboard

    def validate(self) -> None:
        if not 1.0 <= self.max_angle_deg <= 180.0:
            raise ValueError("max_angle_deg deve estar em [1, 180]")
        if not 0.0 <= self.deadzone < 1.0:
            raise ValueError("deadzone deve estar em [0, 1)")
        if not 0.0 < self.smoothing <= 1.0:
            raise ValueError("smoothing deve estar em (0, 1]")
        if self.gear_flash_ms < 0:
            raise ValueError("gear_flash_ms deve ser >= 0")
