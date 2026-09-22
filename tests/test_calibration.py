"""Testes da calibração v2: captura por média + trava-a-trava."""

import time
import unittest

from core.angles import circular_mean
from core.models import ProcessorConfig
from core.steering import SteeringProcessor


def make_proc() -> SteeringProcessor:
    return SteeringProcessor(ProcessorConfig(deadzone=0.0, smoothing=1.0))


class TestCircularMean(unittest.TestCase):
    def test_basica(self):
        self.assertAlmostEqual(circular_mean([10.0, 20.0]), 15.0)

    def test_wrap(self):
        # Média aritmética daria 180 (errado); circular dá ~0.
        self.assertAlmostEqual(circular_mean([359.0, 1.0]), 0.0, places=5)
        self.assertAlmostEqual(circular_mean([350.0, 10.0]), 0.0, places=5)

    def test_unica(self):
        self.assertAlmostEqual(circular_mean([123.0]), 123.0)

    def test_vazia_falha(self):
        with self.assertRaises(ValueError):
            circular_mean([])


class TestCenterCapture(unittest.TestCase):
    def test_media_com_tremor_e_wrap(self):
        p = make_proc()
        p.update_heading(359.0)
        p.start_center_capture(0.5)
        for a in (358.0, 359.0, 0.0, 1.0, 0.0, 359.0):  # mão tremendo no wrap
            p.update_heading(a)
            time.sleep(0.1)
        time.sleep(0.15)
        p.update_heading(0.0)  # dispara a finalização
        snap = p.snapshot()
        self.assertIsNotNone(snap.center)
        assert snap.center is not None
        # Centro deve estar colado no 0/360, longe do 180 da média ingênua.
        self.assertLess(min(snap.center, 360.0 - snap.center), 5.0)
        # A amostra que finalizou a captura já é processada com o centro
        # novo, então o steering fica residual (não exatamente zero).
        self.assertLess(abs(snap.steering), 0.1)
        last = p.last_capture()
        self.assertTrue(last and last["ok"])
        self.assertGreaterEqual(last["samples"], 6)

    def test_status_e_cancel(self):
        p = make_proc()
        p.update_heading(100.0)
        self.assertIsNone(p.capture_status())
        p.start_center_capture(5.0)
        st = p.capture_status()
        self.assertTrue(st and st["active"])
        p.cancel_capture()
        self.assertIsNone(p.capture_status())
        self.assertIsNone(p.snapshot().center)

    def test_duracao_invalida(self):
        p = make_proc()
        p.update_heading(0.0)
        with self.assertRaises(ValueError):
            p.start_center_capture(0.1)
        with self.assertRaises(ValueError):
            p.start_center_capture(99.0)

    def test_sem_leitura_falha(self):
        with self.assertRaises(RuntimeError):
            make_proc().start_center_capture(1.0)


class TestLockToLock(unittest.TestCase):
    def test_ponto_medio_e_curso(self):
        p = make_proc()
        p.update_heading(300.0)
        p.mark_lock("LEFT")
        p.update_heading(60.0)
        p.mark_lock("RIGHT")
        result = p.finish_lock_calibration()
        # De 300° até 60° no sentido horário: +120°; meio = 0°, curso = 60°.
        self.assertAlmostEqual(result["center"], 0.0, places=5)
        self.assertAlmostEqual(result["max_angle_deg"], 60.0)
        snap = p.snapshot()
        self.assertIsNotNone(snap.center)
        assert snap.center is not None
        self.assertAlmostEqual(snap.center, 0.0, places=5)
        # Extremos saturam cheio, meio zera.
        self.assertAlmostEqual(p.update_heading(60.0), 1.0)
        self.assertAlmostEqual(p.update_heading(300.0), -1.0)
        self.assertAlmostEqual(p.update_heading(0.0), 0.0)

    def test_ordem_nao_importa(self):
        p = make_proc()
        p.update_heading(60.0)
        p.mark_lock("RIGHT")
        p.update_heading(300.0)
        p.mark_lock("LEFT")
        result = p.finish_lock_calibration()
        self.assertAlmostEqual(result["center"], 0.0, places=5)
        self.assertAlmostEqual(result["max_angle_deg"], 60.0)

    def test_falta_marca_falha(self):
        p = make_proc()
        p.update_heading(10.0)
        p.mark_lock("LEFT")
        with self.assertRaises(RuntimeError):
            p.finish_lock_calibration()

    def test_travas_proximas_falha(self):
        p = make_proc()
        p.update_heading(10.0)
        p.mark_lock("LEFT")
        p.update_heading(15.0)
        p.mark_lock("RIGHT")
        with self.assertRaises(ValueError):
            p.finish_lock_calibration()

    def test_lado_invalido(self):
        p = make_proc()
        p.update_heading(10.0)
        with self.assertRaises(ValueError):
            p.mark_lock("MIDDLE")

    def test_sem_leitura_falha(self):
        with self.assertRaises(RuntimeError):
            make_proc().mark_lock("LEFT")


if __name__ == "__main__":
    unittest.main()
