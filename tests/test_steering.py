"""Testes do SteeringProcessor + parser do adaptador micro:bit."""

import time
import unittest

from core.models import ProcessorConfig
from core.steering import SteeringProcessor
from inputs.microbit_serial import parse_line


class TestSteeringProcessor(unittest.TestCase):
    def _proc(self, **kw) -> SteeringProcessor:
        params = {"max_angle_deg": 90.0, "deadzone": 0.0, "smoothing": 1.0}
        params.update(kw)
        return SteeringProcessor(ProcessorConfig(**params))

    def test_sem_calibracao_nao_esterca_mas_guarda_bruto(self):
        p = self._proc()
        self.assertEqual(p.update_heading(200), 0.0)
        snap = p.snapshot()
        self.assertAlmostEqual(snap.raw_angle, 200.0)
        self.assertIsNone(snap.center)
        self.assertEqual(snap.steering, 0.0)

    def test_calibracao_e_curso(self):
        p = self._proc()
        p.update_heading(180)
        p.calibrate()
        self.assertAlmostEqual(p.update_heading(180), 0.0)
        self.assertAlmostEqual(p.update_heading(225), 0.5)   # +45° → metade
        self.assertAlmostEqual(p.update_heading(270), 1.0)   # +90° → cheio
        self.assertAlmostEqual(p.update_heading(135), -0.5)
        self.assertAlmostEqual(p.update_heading(90), -1.0)

    def test_saturacao_alem_do_maximo(self):
        p = self._proc()
        p.update_heading(0)
        p.calibrate()
        self.assertAlmostEqual(p.update_heading(170), 1.0)  # +170 satura
        self.assertAlmostEqual(p.update_heading(190), -1.0)  # -170 satura

    def test_wrap_no_processador(self):
        p = self._proc()
        p.update_heading(355)
        p.calibrate()
        # 355 → 5 cruza o 0: deve dar +10° → 10/90 ≈ 0.111, não −0.98
        self.assertAlmostEqual(p.update_heading(5), 10 / 90, places=5)

    def test_zona_morta(self):
        p = self._proc(deadzone=0.1)
        p.update_heading(100)
        p.calibrate()
        p.update_heading(104)  # 4°/90 ≈ 0.044 < 0.1 → 0
        self.assertEqual(p.snapshot().steering, 0.0)

    def test_suavizacao_ema(self):
        p = self._proc(smoothing=0.5)
        p.update_heading(0)
        p.calibrate()          # ancora suavizado em 0
        p.update_heading(90)   # alvo 1.0 → EMA: 0.5*1 + 0.5*0 = 0.5
        self.assertAlmostEqual(p.snapshot().steering, 0.5)
        p.update_heading(90)   # 0.5*1 + 0.5*0.5 = 0.75
        self.assertAlmostEqual(p.snapshot().steering, 0.75)

    def test_direcao_continua_nao_e_tecla(self):
        p = self._proc()
        p.update_heading(0)
        p.calibrate()
        vistos = {p.update_heading(a) for a in (10, 20, 30, 40, 50)}
        self.assertGreater(len(vistos), 3)  # granular, não 3 estados

    def test_marchas_independentes(self):
        p = SteeringProcessor(ProcessorConfig(gear_flash_ms=60_000))
        p.gear_event("UP")
        snap = p.snapshot()
        self.assertTrue(snap.gear_up)
        self.assertFalse(snap.gear_down)
        self.assertEqual(snap.gear_up_count, 1)
        p.gear_event("DOWN")
        snap = p.snapshot()
        self.assertTrue(snap.gear_down)
        self.assertEqual(snap.gear_down_count, 1)

    def test_marcha_expira(self):
        p = SteeringProcessor(ProcessorConfig(gear_flash_ms=30))
        p.gear_event("UP")
        self.assertTrue(p.snapshot().gear_up)
        time.sleep(0.06)
        self.assertFalse(p.snapshot().gear_up)
        self.assertEqual(p.snapshot().gear_up_count, 1)

    def test_calibrar_sem_leitura_falha(self):
        with self.assertRaises(RuntimeError):
            self._proc().calibrate()

    def test_config_invalida_rejeitada(self):
        p = self._proc()
        with self.assertRaises(ValueError):
            p.update_config(max_angle_deg=0)
        with self.assertRaises(ValueError):
            p.update_config(deadzone=1.5)
        with self.assertRaises(ValueError):
            p.update_config(smoothing=0)


class TestParseLine(unittest.TestCase):
    def test_steer(self):
        r = parse_line("STEER:217")
        self.assertIsNotNone(r)
        assert r is not None
        self.assertAlmostEqual(r.heading_deg, 217.0)
        self.assertIsNone(r.gear)

    def test_steer_com_ruido(self):
        r = parse_line("  STEER:45\r\n")
        assert r is not None
        self.assertAlmostEqual(r.heading_deg, 45.0)

    def test_steer_enrola_360(self):
        r = parse_line("STEER:360")
        assert r is not None
        self.assertAlmostEqual(r.heading_deg, 0.0)

    def test_gear(self):
        self.assertEqual(parse_line("GEAR:UP").gear, "UP")
        self.assertEqual(parse_line("gear:down").gear, "DOWN")  # case-insensitive

    def test_gear_invalido(self):
        with self.assertRaises(ValueError):
            parse_line("GEAR:SIDEWAYS")

    def test_steer_invalido(self):
        with self.assertRaises(ValueError):
            parse_line("STEER:abc")

    def test_lixo_ignorado(self):
        self.assertIsNone(parse_line("hello micro:bit"))
        self.assertIsNone(parse_line(""))


if __name__ == "__main__":
    unittest.main()
