"""Testes dos pedais: parser BRAKE/ACCEL + mapeamento mm → 0..1."""

import unittest

from core.pedals import PedalChannel, PedalConfig
from core.steering import SteeringProcessor
from inputs.microbit_serial import parse_line
from outputs.uinput_gamepad import pedal_to_trigger


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s: float):
        self.t += s


class TestParsePedals(unittest.TestCase):
    def test_brake(self):
        r = parse_line("BRAKE:34")
        assert r is not None
        self.assertAlmostEqual(r.brake_mm, 34.0)
        self.assertIsNone(r.accel_mm)

    def test_accel(self):
        r = parse_line("ACCEL:41")
        assert r is not None
        self.assertAlmostEqual(r.accel_mm, 41.0)

    def test_zero_e_valido_no_parser_invalido_no_nucleo(self):
        r = parse_line("BRAKE:0")  # sem eco: parser aceita, núcleo trata
        assert r is not None
        self.assertAlmostEqual(r.brake_mm, 0.0)

    def test_invalido(self):
        with self.assertRaises(ValueError):
            parse_line("BRAKE:abc")
        with self.assertRaises(ValueError):
            parse_line("ACCEL:")

    def test_legado_intacto(self):
        self.assertAlmostEqual(parse_line("STEER:217").heading_deg, 217.0)
        self.assertEqual(parse_line("GEAR:UP").gear, "UP")


class TestPedalChannel(unittest.TestCase):
    def _ch(self, **kw):
        cfg = PedalConfig(far_mm=50.0, near_mm=20.0, smoothing=1.0, hold_ms=250)
        for k, v in kw.items():
            setattr(cfg, k, v)
        clock = FakeClock()
        return PedalChannel(cfg, clock=clock), clock

    def test_curva(self):
        ch, _ = self._ch()
        self.assertAlmostEqual(ch.update(60.0), 0.0)   # longe = solto
        self.assertAlmostEqual(ch.update(50.0), 0.0)   # borda
        self.assertAlmostEqual(ch.update(35.0), 0.5)   # meio
        self.assertAlmostEqual(ch.update(20.0), 1.0)   # perto = fundo
        self.assertAlmostEqual(ch.update(5.0), 1.0)    # satura

    def test_none_mantem(self):
        ch, _ = self._ch()
        ch.update(20.0)
        self.assertAlmostEqual(ch.update(None), 1.0)

    def test_invalido_congela_e_depois_solta(self):
        ch, clock = self._ch()
        ch.update(20.0)  # fundo
        clock.advance(0.1)
        self.assertAlmostEqual(ch.update(0.0), 1.0)  # dentro do hold: congela
        clock.advance(0.3)
        self.assertAlmostEqual(ch.update(0.0), 0.0)  # passou o hold: solta

    def test_sem_historico_invalido_e_zero(self):
        ch, _ = self._ch()
        self.assertAlmostEqual(ch.update(0.0), 0.0)

    def test_suavizacao(self):
        ch, _ = self._ch(smoothing=0.5)
        ch.update(50.0)  # alvo 0
        self.assertAlmostEqual(ch.update(20.0), 0.5)  # meio caminho p/ 1

    def test_config_invalida(self):
        with self.assertRaises(ValueError):
            PedalConfig(far_mm=20.0, near_mm=50.0).validate()


class TestProcessorPedals(unittest.TestCase):
    def test_integracao(self):
        p = SteeringProcessor()
        p.update_pedals(20.0, 50.0, None)
        b, a, c = p.update_pedals(20.0, 50.0, None)  # EMA converge (smoothing padrão 0.5)
        self.assertGreater(b, 0.7)
        self.assertLess(a, 0.1)
        snap = p.snapshot()
        self.assertGreater(snap.brake, 0.7)
        self.assertIn("brake", snap.to_dict())


class TestTrigger(unittest.TestCase):
    def test_limites(self):
        self.assertEqual(pedal_to_trigger(0.0), 0)
        self.assertEqual(pedal_to_trigger(1.0), 255)
        self.assertEqual(pedal_to_trigger(0.5), 128)
        self.assertEqual(pedal_to_trigger(9.0), 255)
        self.assertEqual(pedal_to_trigger(-1.0), 0)


if __name__ == "__main__":
    unittest.main()
