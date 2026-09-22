"""Núcleo do volante: trabalha SOMENTE com dados normalizados.

Pipeline interno por amostra de ângulo::

    raw (0..360) → relativo (-180..+180) → curso (-1..1)
        → zona morta → suavização (EMA) → steering final

A direção NUNCA é convertida em teclas; permanece analógica contínua.
Botões de marcha (UP/DOWN) são eventos independentes.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from .angles import apply_deadzone, circular_mean, clamp, normalize_compass, relative_angle
from .models import ProcessorConfig, WheelState
from .pedals import PedalChannel, PedalConfig

log = logging.getLogger(__name__)


class SteeringProcessor:
    """Converte leituras normalizadas em estado de volante."""

    def __init__(self, config: Optional[ProcessorConfig] = None,
                 pedal_config: Optional[PedalConfig] = None) -> None:
        self._config = config or ProcessorConfig()
        self._config.validate()
        self._pedal_config = pedal_config or PedalConfig()
        self._pedal_config.validate()
        self._lock = threading.Lock()
        self._raw: Optional[float] = None
        self._center: Optional[float] = None
        self._relative: Optional[float] = None
        self._steering: float = 0.0
        self._smoothed: Optional[float] = None
        self._gear_up_until: float = 0.0
        self._gear_down_until: float = 0.0
        self._gear_up_count: int = 0
        self._gear_down_count: int = 0
        self._shift_up_until: float = 0.0
        self._shift_down_until: float = 0.0
        self._shift_up_count: int = 0
        self._shift_down_count: int = 0
        self._auto_mode: bool = False
        self._handbrake: bool = False
        self._brake = PedalChannel(self._pedal_config)
        self._accel = PedalChannel(self._pedal_config)
        self._clutch = PedalChannel(self._pedal_config)
        # Captura de centro (média de N segundos com o volante parado).
        self._capture_until: Optional[float] = None
        self._capture_samples: list[float] = []
        self._capture_error: Optional[str] = None
        self._last_capture: Optional[dict] = None
        # Trava-a-trava: marcas dos extremos físicos.
        self._locks: dict[str, float] = {}

    # -- configuração -------------------------------------------------
    @property
    def config(self) -> ProcessorConfig:
        with self._lock:
            return ProcessorConfig(
                max_angle_deg=self._config.max_angle_deg,
                deadzone=self._config.deadzone,
                smoothing=self._config.smoothing,
                gear_flash_ms=self._config.gear_flash_ms,
            )

    def update_config(
        self,
        *,
        max_angle_deg: Optional[float] = None,
        deadzone: Optional[float] = None,
        smoothing: Optional[float] = None,
        pedal_far_mm: Optional[float] = None,
        pedal_near_mm: Optional[float] = None,
        pedal_smoothing: Optional[float] = None,
    ) -> ProcessorConfig:
        with self._lock:
            if max_angle_deg is not None:
                self._config.max_angle_deg = float(max_angle_deg)
            if deadzone is not None:
                self._config.deadzone = float(deadzone)
            if smoothing is not None:
                self._config.smoothing = float(smoothing)
            self._config.validate()
            if pedal_far_mm is not None:
                self._pedal_config.far_mm = float(pedal_far_mm)
            if pedal_near_mm is not None:
                self._pedal_config.near_mm = float(pedal_near_mm)
            if pedal_smoothing is not None:
                self._pedal_config.smoothing = float(pedal_smoothing)
            self._pedal_config.validate()
            log.info(
                "config atualizada: max_angle=%.1f deadzone=%.3f smoothing=%.3f "
                "pedal_far=%.0f pedal_near=%.0f",
                self._config.max_angle_deg,
                self._config.deadzone,
                self._config.smoothing,
                self._pedal_config.far_mm,
                self._pedal_config.near_mm,
            )
            return self._config

    @property
    def pedal_config(self) -> PedalConfig:
        with self._lock:
            return PedalConfig(
                far_mm=self._pedal_config.far_mm,
                near_mm=self._pedal_config.near_mm,
                smoothing=self._pedal_config.smoothing,
                hold_ms=self._pedal_config.hold_ms,
            )

    # -- calibração ----------------------------------------------------
    def calibrate(self) -> float:
        """Define a orientação atual como centro. Retorna o centro."""
        with self._lock:
            if self._raw is None:
                raise RuntimeError("sem leitura de ângulo ainda; gire o dispositivo primeiro")
            self._center = normalize_compass(self._raw)
            # Reancora a suavização para evitar salto após calibrar.
            self._smoothed = 0.0
            self._relative = 0.0
            self._steering = 0.0
            self._capture_until = None
            self._capture_samples = []
            log.info("centro calibrado em %.1f°", self._center)
            return self._center

    def start_center_capture(self, duration_s: float = 2.0) -> dict:
        """Inicia captura do centro por média (segure o volante parado).

        Durante ``duration_s`` segundos, cada amostra de ângulo é
        acumulada; ao final, o centro é a média circular das amostras,
        imune ao tremor da mão e ao wrap 359°→0°.
        """
        if not 0.5 <= float(duration_s) <= 10.0:
            raise ValueError("duração da captura deve estar em [0.5, 10]s")
        with self._lock:
            if self._raw is None:
                raise RuntimeError("sem leitura de ângulo ainda; gire o dispositivo primeiro")
            self._capture_until = time.monotonic() + float(duration_s)
            self._capture_samples = []
            self._capture_error = None
            log.info("captura de centro iniciada (%.1fs, segure parado)", duration_s)
            return {"duration_s": float(duration_s)}

    def cancel_capture(self) -> None:
        with self._lock:
            self._capture_until = None
            self._capture_samples = []

    def capture_status(self) -> Optional[dict]:
        """None quando ocioso; senão progresso da captura ativa."""
        with self._lock:
            if self._capture_until is None:
                return None
            return {
                "active": True,
                "remaining_s": round(max(0.0, self._capture_until - time.monotonic()), 2),
                "samples": len(self._capture_samples),
            }

    def last_capture(self) -> Optional[dict]:
        with self._lock:
            return dict(self._last_capture) if self._last_capture else None

    def _maybe_finalize_capture(self) -> None:
        """Chamado com o lock já adquirido, dentro de update_heading."""
        if self._capture_until is None or time.monotonic() < self._capture_until:
            return
        samples = self._capture_samples
        self._capture_until = None
        self._capture_samples = []
        try:
            center = circular_mean(samples)
        except ValueError as exc:
            self._capture_error = str(exc)
            self._last_capture = {"ok": False, "error": str(exc), "samples": len(samples)}
            log.warning("captura de centro falhou: %s", exc)
            return
        self._center = center
        self._smoothed = 0.0
        self._relative = 0.0
        self._steering = 0.0
        self._capture_error = None
        self._last_capture = {"ok": True, "center": center, "samples": len(samples)}
        log.info("centro calibrado por média: %.1f° (%d amostras)", center, len(samples))

    # -- trava-a-trava ---------------------------------------------------
    def mark_lock(self, side: str) -> float:
        """Marca o ângulo bruto atual como extremo físico LEFT/RIGHT."""
        s = side.strip().upper()
        if s not in ("LEFT", "RIGHT"):
            raise ValueError("side deve ser LEFT ou RIGHT")
        with self._lock:
            if self._raw is None:
                raise RuntimeError("sem leitura de ângulo ainda; gire o dispositivo primeiro")
            self._locks[s] = normalize_compass(self._raw)
            log.info("trava %s marcada em %.1f°", s, self._locks[s])
            return self._locks[s]

    def lock_marks(self) -> dict:
        with self._lock:
            return dict(self._locks)

    def clear_locks(self) -> None:
        with self._lock:
            self._locks = {}

    def finish_lock_calibration(self) -> dict:
        """Calcula centro e curso a partir dos extremos marcados.

        O centro é o ponto médio circular entre as travas e o curso
        (max_angle) é metade da distância entre elas — ou seja, o curso
        se adapta ao giro confortável do piloto, sem precisar girar 90°.
        A ordem das marcas não importa.
        """
        with self._lock:
            if "LEFT" not in self._locks or "RIGHT" not in self._locks:
                raise RuntimeError("marque a trava esquerda E a direita antes de concluir")
            left = self._locks["LEFT"]
            right = self._locks["RIGHT"]
            span = relative_angle(right, left)
            half = abs(span) / 2.0
            if half < 10.0:
                raise ValueError(
                    f"travas próximas demais ({abs(span):.0f}°); "
                    "gire bem para cada lado antes de marcar"
                )
            if half > 175.0:
                raise ValueError("travas quase opostas demais; use um curso menor que 350°")
            center = (left + span / 2.0) % 360.0
            self._center = center
            self._config.max_angle_deg = round(half, 1)
            self._smoothed = 0.0
            self._relative = 0.0
            self._steering = 0.0
            self._locks = {}
            log.info(
                "trava-a-trava: centro=%.1f° curso=±%.1f°", center, self._config.max_angle_deg
            )
            return {"center": center, "max_angle_deg": self._config.max_angle_deg}

    def reset_calibration(self) -> None:
        with self._lock:
            self._center = None
            self._relative = None
            self._smoothed = None
            self._steering = 0.0
            self._capture_until = None
            self._capture_samples = []
            self._locks = {}

    # -- entradas normalizadas ----------------------------------------
    def update_heading(self, raw_deg: float) -> float:
        """Processa um ângulo bruto 0..360 e retorna o steering -1..1."""
        raw = normalize_compass(float(raw_deg))
        with self._lock:
            self._raw = raw
            if self._capture_until is not None:
                self._capture_samples.append(raw)
                self._maybe_finalize_capture()
            if self._center is None:
                # Sem calibração: mostra o bruto, mas não esterça.
                self._relative = None
                self._steering = 0.0
                self._smoothed = None
                return 0.0
            rel = relative_angle(raw, self._center)
            target = clamp(rel / self._config.max_angle_deg, -1.0, 1.0)
            target = apply_deadzone(target, self._config.deadzone)
            alpha = self._config.smoothing
            if self._smoothed is None:
                self._smoothed = target
            else:
                self._smoothed = alpha * target + (1.0 - alpha) * self._smoothed
            self._relative = rel
            self._steering = clamp(self._smoothed, -1.0, 1.0)
            return self._steering

    def update_pedals(
        self,
        brake_mm: Optional[float] = None,
        accel_mm: Optional[float] = None,
        clutch_mm: Optional[float] = None,
    ) -> tuple[float, float, float]:
        """Processa distâncias dos pedais (mm) → (freio, acel, embre) 0…1."""
        with self._lock:
            b = self._brake.update(brake_mm)
            a = self._accel.update(accel_mm)
            c = self._clutch.update(clutch_mm)
            return b, a, c

    def set_mode(self, auto: bool) -> bool:
        """Define câmbio automático (True) ou manual (False)."""
        with self._lock:
            self._auto_mode = bool(auto)
            log.info("modo: %s", "AUTOMÁTICO" if auto else "MANUAL")
            return self._auto_mode

    def set_handbrake(self, on: bool) -> bool:
        with self._lock:
            self._handbrake = bool(on)
            return self._handbrake

    def shift_event(self, shift: str) -> bool:
        """Marcha do câmbio sequencial. Retorna True se aceita.

        Regra de carro real: só entra com embreagem pressionada
        (clutch >= 0.5) e em modo MANUAL. Caso contrário é ignorada.
        """
        with self._lock:
            s = shift.strip().upper()
            if s not in ("UP", "DOWN"):
                raise ValueError(f"câmbio inválido: {shift!r}")
            if self._auto_mode:
                log.debug("SHIFT ignorado: modo automático")
                return False
            if self._clutch.value < 0.5:
                log.debug("SHIFT ignorado: embreagem solta (%.2f)", self._clutch.value)
                return False
            now = time.monotonic()
            hold_s = self._config.gear_flash_ms / 1000.0
            if s == "UP":
                self._shift_up_until = now + hold_s
                self._shift_up_count += 1
            else:
                self._shift_down_until = now + hold_s
                self._shift_down_count += 1
            return True

    def gear_event(self, gear: str) -> None:
        """Registra um evento de botão UP/DOWN (independente da direção)."""
        now = time.monotonic()
        hold_s = self._config.gear_flash_ms / 1000.0
        with self._lock:
            g = gear.strip().upper()
            if g == "UP":
                self._gear_up_until = now + hold_s
                self._gear_up_count += 1
            elif g == "DOWN":
                self._gear_down_until = now + hold_s
                self._gear_down_count += 1
            else:
                raise ValueError(f"botão de marcha inválido: {gear!r}")

    # -- saída genérica -------------------------------------------------
    def snapshot(
        self,
        *,
        connected: bool = False,
        port: Optional[str] = None,
        last_seen: Optional[float] = None,
    ) -> WheelState:
        """Estado atual (botões expiram após gear_flash_ms)."""
        now = time.monotonic()
        with self._lock:
            return WheelState(
                raw_angle=self._raw,
                center=self._center,
                relative_angle=self._relative,
                steering=self._steering,
                brake=self._brake.value,
                accel=self._accel.value,
                gear_up=now < self._gear_up_until,
                gear_down=now < self._gear_down_until,
                gear_up_count=self._gear_up_count,
                gear_down_count=self._gear_down_count,
                shift_up=now < self._shift_up_until,
                shift_down=now < self._shift_down_until,
                shift_up_count=self._shift_up_count,
                shift_down_count=self._shift_down_count,
                clutch=self._clutch.value,
                auto_mode=self._auto_mode,
                handbrake=self._handbrake,
                connected=connected,
                port=port,
                last_seen=last_seen,
            )
