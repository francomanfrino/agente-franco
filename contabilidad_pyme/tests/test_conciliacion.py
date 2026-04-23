"""
Unit tests for the reconciliation engine.
Run with: python -m pytest tests/ -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core.conciliacion import (
    conciliar, MovimientoDTO, FacturaDTO,
    _cuit_in_text, _amounts_match, _within_date_window,
    detectar_transferencia_interna,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

def make_mov(id: int, credito: float, fecha: str = "2024-03-15",
             descripcion: str = "Transferencia recibida", debito: float = 0) -> MovimientoDTO:
    return MovimientoDTO(id=id, fecha=fecha, descripcion=descripcion,
                         credito=credito, debito=debito)


def make_fac(id: int, total: float, cuit: str = "20123456789",
             razon_social: str = "CLIENTE SA", fecha_emision: str = "2024-03-01",
             fecha_vencimiento: str = "2024-03-30",
             monto_cobrado: float = 0) -> FacturaDTO:
    return FacturaDTO(
        id=id, nro_factura=f"0001-{id:08d}",
        fecha_emision=fecha_emision, fecha_vencimiento=fecha_vencimiento,
        cuit=cuit, razon_social=razon_social,
        total=total, monto_cobrado=monto_cobrado,
        estado="pendiente", tipo="emitida",
    )


# ── Tests: helpers ────────────────────────────────────────────────────────────

class TestHelpers:
    def test_amounts_match_exact(self):
        assert _amounts_match(1000.00, 1000.00)

    def test_amounts_match_tolerance(self):
        assert _amounts_match(1000.005, 1000.00)

    def test_amounts_no_match(self):
        assert not _amounts_match(1000.10, 1000.00)

    def test_cuit_in_text_plain(self):
        assert _cuit_in_text("20123456789", "PAGO DE 20123456789 CLIENTE SA")

    def test_cuit_in_text_formatted(self):
        assert _cuit_in_text("20123456789", "CUIT 20-12345678-9 CLIENTE")

    def test_cuit_not_in_text(self):
        assert not _cuit_in_text("20123456789", "PAGO DE OTRO CLIENTE")

    def test_cuit_empty(self):
        assert not _cuit_in_text("", "cualquier texto")

    def test_date_window_within(self):
        assert _within_date_window("2024-03-28", "2024-03-30", "2024-03-01", days=5)

    def test_date_window_outside(self):
        assert not _within_date_window("2024-04-10", "2024-03-30", "2024-03-01", days=5)

    def test_date_window_no_vto(self):
        # No vencimiento → should not discard
        assert _within_date_window("2024-03-28", None, "2024-03-01", days=5)


# ── Tests: conciliar() ────────────────────────────────────────────────────────

class TestConciliar:

    def test_exact_match(self):
        movs = [make_mov(1, 1000.00, fecha="2024-03-28")]
        facs = [make_fac(1, 1000.00)]
        matches, unmatched_mov, unmatched_fac = conciliar(movs, facs)
        assert len(matches) == 1
        assert matches[0].metodo == "automatico_exacto"
        assert matches[0].confianza == 1.0
        assert 1 not in unmatched_mov
        assert 1 not in unmatched_fac

    def test_no_match_wrong_amount(self):
        movs = [make_mov(1, 500.00)]
        facs = [make_fac(1, 1000.00)]
        matches, unmatched_mov, unmatched_fac = conciliar(movs, facs)
        assert len(matches) == 0
        assert 1 in unmatched_mov
        assert 1 in unmatched_fac

    def test_cuit_match(self):
        movs = [make_mov(1, 5000.00, descripcion="CREDITO 20123456789 ACME SA")]
        facs = [make_fac(1, 5000.00, cuit="20123456789",
                         fecha_vencimiento="2024-04-30")]  # outside date window
        matches, _, _ = conciliar(movs, facs)
        assert len(matches) == 1
        assert matches[0].metodo == "automatico_cuit"

    def test_fuzzy_match(self):
        movs = [make_mov(1, 2500.00, descripcion="PAGO ACME ARGENTINA SRL")]
        facs = [make_fac(1, 2500.00, razon_social="ACME ARGENTINA SRL",
                         cuit="20999999999", fecha_vencimiento="2024-04-30")]
        matches, _, _ = conciliar(movs, facs)
        assert len(matches) == 1
        assert matches[0].metodo == "automatico_fuzzy"
        assert matches[0].confianza >= 0.85

    def test_fuzzy_below_threshold(self):
        movs = [make_mov(1, 2500.00, descripcion="PAGO EMPRESA TOTALMENTE DIFERENTE")]
        facs = [make_fac(1, 2500.00, razon_social="ACME ARGENTINA SRL",
                         cuit="20999999999", fecha_vencimiento="2024-04-30")]
        matches, unmatched_mov, _ = conciliar(movs, facs, fuzzy_threshold=85.0)
        # Should NOT match due to low similarity
        # (depends on implementation; at minimum, check no high-confidence match)
        for m in matches:
            assert m.confianza < 0.85 or m.metodo != "automatico_fuzzy"

    def test_partial_payment(self):
        movs = [make_mov(1, 600.00), make_mov(2, 400.00)]
        facs = [make_fac(1, 1000.00, fecha_vencimiento="2024-04-30")]
        matches, unmatched_mov, unmatched_fac = conciliar(movs, facs)
        assert len(matches) == 2
        assert all(m.metodo == "automatico_parcial" for m in matches)
        assert 1 not in unmatched_fac

    def test_partial_three_payments(self):
        movs = [make_mov(1, 300.00), make_mov(2, 300.00), make_mov(3, 400.00)]
        facs = [make_fac(1, 1000.00, fecha_vencimiento="2024-04-30")]
        matches, _, unmatched_fac = conciliar(movs, facs)
        assert 1 not in unmatched_fac
        assert sum(m.monto_aplicado for m in matches) == pytest.approx(1000.00)

    def test_no_double_assignment(self):
        """A single movement cannot match two invoices."""
        movs = [make_mov(1, 1000.00)]
        facs = [make_fac(1, 1000.00), make_fac(2, 1000.00)]
        matches, _, _ = conciliar(movs, facs)
        assert len(matches) == 1

    def test_internal_transfer_excluded(self):
        movs = [MovimientoDTO(
            id=1, fecha="2024-03-15", descripcion="TRANSFERENCIA ENTRE CUENTAS",
            credito=5000.00, debito=0, es_transferencia_interna=True
        )]
        facs = [make_fac(1, 5000.00)]
        matches, unmatched_mov, _ = conciliar(movs, facs)
        assert len(matches) == 0

    def test_already_conciliado_excluded(self):
        movs = [MovimientoDTO(
            id=1, fecha="2024-03-15", descripcion="Pago cliente",
            credito=1000.00, debito=0, conciliado=True
        )]
        facs = [make_fac(1, 1000.00)]
        matches, unmatched_mov, _ = conciliar(movs, facs)
        assert len(matches) == 0

    def test_retenciones_probable_match(self):
        """Invoice 1000, received 850 (15% retenciones) → probable match."""
        movs = [make_mov(1, 850.00, fecha="2024-03-28")]
        facs = [make_fac(1, 1000.00)]
        matches, _, _ = conciliar(movs, facs)
        net_matches = [m for m in matches if m.factura_id == 1 and m.movimiento_id == 1]
        assert len(net_matches) == 1
        assert net_matches[0].es_probable is True

    def test_multiple_invoices_multiple_movements(self):
        movs = [make_mov(1, 1000.00, fecha="2024-03-28"),
                make_mov(2, 2000.00, fecha="2024-03-29"),
                make_mov(3, 3000.00, fecha="2024-04-01")]
        facs = [make_fac(1, 1000.00), make_fac(2, 2000.00), make_fac(3, 3000.00)]
        matches, unmatched_mov, unmatched_fac = conciliar(movs, facs)
        assert len(matches) == 3
        assert unmatched_mov == []
        assert unmatched_fac == []

    def test_empty_inputs(self):
        matches, um, uf = conciliar([], [])
        assert matches == []
        assert um == []
        assert uf == []

    def test_empty_movements(self):
        facs = [make_fac(1, 1000.00)]
        matches, um, uf = conciliar([], facs)
        assert matches == []
        assert 1 in uf

    def test_empty_facturas(self):
        movs = [make_mov(1, 1000.00)]
        matches, um, uf = conciliar(movs, [])
        assert matches == []
        assert 1 in um


# ── Tests: detectar_transferencia_interna ────────────────────────────────────

class TestTransferenciaInterna:
    def test_keyword_match(self):
        assert detectar_transferencia_interna("TRANSF ENTRE CTAS OWN", "")

    def test_cuit_propio(self):
        assert detectar_transferencia_interna("PAGO CUIT 20123456789", "20123456789")

    def test_normal_payment(self):
        assert not detectar_transferencia_interna("COBRO CLIENTE SRL", "20123456789")
