"""The leakage guard as a CI test. It is the project's most valuable artefact.

It needs the database up with features computed. Skipped if there are none.
"""

import pytest

from crucible.leakcheck import check
from crucible.signals import CORTES, clasificar

pytestmark = pytest.mark.skipif(
    __import__("os").environ.get("CRUCIBLE_SKIP_DB") == "1", reason="no database"
)


def _has_data(symbol="copper") -> bool:
    try:
        import psycopg
        from crucible.leakcheck import DSN
        with psycopg.connect(DSN, connect_timeout=3) as c, c.cursor() as cur:
            cur.execute("SELECT count(*) FROM feat.feature WHERE symbol=%s", (symbol,))
            return cur.fetchone()[0] > 1000
    except Exception:
        return False


@pytest.mark.parametrize("symbol", ["copper", "gold", "natgas", "eurusd"])
def test_no_feature_looks_into_the_future(symbol):
    """Recomputes each feature truncating the series at each origin_ts, requiring the same
    value.

    If a feature used later data, truncation takes it away and the value changes.
    """
    if not _has_data(symbol):
        pytest.skip("no features computed")
    leaks = check(symbol, muestras=25)
    assert not leaks, "\n".join(
        f"{f.symbol} {f.origin_ts} {f.feature}: {f.con_futuro} vs {f.sin_futuro}"
        for f in leaks[:6]
    )


def test_the_guard_detects_an_injected_leak():
    """A guard that never finds anything is indistinguishable from a broken guard.

    A CENTRED mean is computed on purpose (it uses 10 later days) and the guard is required
    to report it. If this test ever starts passing with no findings, the guard broke and
    that has to be fixed before anything else.
    """
    if not _has_data():
        pytest.skip("no features computed")
    leaks = check("copper", muestras=25, inyectar_fuga=True)
    assert leaks, "the guard did NOT detect a centred mean: it is broken"
    assert all(f.delta > 0 for f in leaks)


# ── the signal ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("pos,esperado", [
    (0.0, "muy_barato"), (0.19, "muy_barato"), (0.20, "barato"),
    (0.45, "normal"), (0.75, "caro"), (0.95, "muy_caro"), (1.0, "muy_caro"),
])
def test_the_bands_cover_the_whole_range(pos, esperado):
    assert clasificar(pos) == esperado


def test_the_cut_points_are_quintiles_without_gaps():
    # Chosen before seeing the backtest. Moving them afterwards would be fitting the
    # signal to the very data it is evaluated against.
    assert [c[1] for c in CORTES] == [0.0, 0.2, 0.4, 0.6, 0.8]
    for a, b in zip(CORTES, CORTES[1:]):
        assert a[2] == b[1], "there is a gap between bands"


def test_without_a_position_there_is_no_band():
    assert clasificar(None) is None
