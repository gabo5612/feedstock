"""El guard de fuga como test de CI. Es el artefacto que mas vale del proyecto.

Necesita la base levantada con features calculadas. Se saltea si no hay.
"""

import pytest

from crucible.leakcheck import check
from crucible.signals import CORTES, clasificar

pytestmark = pytest.mark.skipif(
    __import__("os").environ.get("CRUCIBLE_SKIP_DB") == "1", reason="sin base"
)


def _hay_datos(symbol="copper") -> bool:
    try:
        import psycopg
        from crucible.leakcheck import DSN
        with psycopg.connect(DSN, connect_timeout=3) as c, c.cursor() as cur:
            cur.execute("SELECT count(*) FROM feat.feature WHERE symbol=%s", (symbol,))
            return cur.fetchone()[0] > 1000
    except Exception:
        return False


@pytest.mark.parametrize("symbol", ["copper", "gold", "natgas", "eurusd"])
def test_ninguna_feature_mira_el_futuro(symbol):
    """Recalcula cada feature truncando la serie en cada origin_ts y exige el mismo valor.

    Si una feature usara un dato posterior, el truncado se lo saca y el valor cambia.
    """
    if not _hay_datos(symbol):
        pytest.skip("sin features calculadas")
    fugas = check(symbol, muestras=25)
    assert not fugas, "\n".join(
        f"{f.symbol} {f.origin_ts} {f.feature}: {f.con_futuro} vs {f.sin_futuro}"
        for f in fugas[:6]
    )


def test_el_guard_detecta_una_fuga_inyectada():
    """Un guard que nunca encuentra nada es indistinguible de un guard roto.

    Se calcula a proposito una media CENTRADA (usa 10 dias posteriores) y se exige que
    el guard la denuncie. Si este test empieza a pasar sin hallazgos, el guard se rompio
    y hay que arreglarlo antes que nada.
    """
    if not _hay_datos():
        pytest.skip("sin features calculadas")
    fugas = check("copper", muestras=25, inyectar_fuga=True)
    assert fugas, "el guard NO detecto una media centrada: esta roto"
    assert all(f.delta > 0 for f in fugas)


# ── la senal ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("pos,esperado", [
    (0.0, "muy_barato"), (0.19, "muy_barato"), (0.20, "barato"),
    (0.45, "normal"), (0.75, "caro"), (0.95, "muy_caro"), (1.0, "muy_caro"),
])
def test_las_bandas_cubren_todo_el_rango(pos, esperado):
    assert clasificar(pos) == esperado


def test_los_cortes_son_quintiles_sin_huecos():
    # Elegidos antes de ver el backtest. Moverlos despues seria ajustar la senal a los
    # datos con los que se la evalua.
    assert [c[1] for c in CORTES] == [0.0, 0.2, 0.4, 0.6, 0.8]
    for a, b in zip(CORTES, CORTES[1:]):
        assert a[2] == b[1], "hay un hueco entre bandas"


def test_sin_posicion_no_hay_banda():
    assert clasificar(None) is None
