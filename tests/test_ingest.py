"""Tests de la ingesta. Sin red: la fuente se reemplaza por un doble.

Lo que se prueba es la logica que protege el dataset, no que Yahoo responda.
"""

from datetime import datetime, timezone

import pytest

from crucible.ingest import VerificationError, verify_name
from crucible.instruments import BY_SYMBOL, INSTRUMENTS, TRAMPAS, Instrument
from crucible.sources.base import Bar, SourceError
from crucible.sources.yahoo import YahooAdapter


class FuenteFalsa:
    name = "falsa"

    def __init__(self, nombre: str):
        self._nombre = nombre

    def display_name(self, ticker: str) -> str:
        return self._nombre

    def fetch(self, ticker, start, end, interval="1d"):
        return []


# ── El guard de nombre: lo que impide contaminar el dataset en silencio ──────
def test_el_nombre_correcto_pasa():
    inst = BY_SYMBOL["copper"]
    assert verify_name(FuenteFalsa("Copper Dec 26"), inst) == "Copper Dec 26"


def test_zn_f_no_puede_entrar_como_zinc():
    """El caso real. `ZN=F` devuelve el bono del Tesoro a 10 anos, no zinc.

    Sin esta comprobacion entraria como zinc, contaminaria el dataset de metales y no
    habria NINGUNA senal: un modelo entrenado encima daria numeros plausibles y falsos.
    """
    zinc_falso = Instrument("zinc", "yahoo", "ZN=F", "Zinc", "metal")
    with pytest.raises(VerificationError, match="no contiene"):
        verify_name(FuenteFalsa("10-Year T-Note Futures,Dec-2026"), zinc_falso)


def test_el_mensaje_del_guard_dice_que_no_se_ingirio_nada():
    with pytest.raises(VerificationError, match="NO se ingirio nada"):
        verify_name(FuenteFalsa("Otra cosa"), BY_SYMBOL["gold"])


def test_la_comparacion_no_distingue_mayusculas():
    assert verify_name(FuenteFalsa("COPPER DEC 26"), BY_SYMBOL["copper"])


def test_la_trampa_conocida_esta_documentada():
    assert "ZN=F" in TRAMPAS and "zinc" in TRAMPAS["ZN=F"].lower()
    # Y ningun instrumento del registro la usa.
    assert "ZN=F" not in {i.source_ticker for i in INSTRUMENTS}


# ── El registro ─────────────────────────────────────────────────────────────
def test_son_doce_instrumentos_con_simbolo_unico():
    assert len(INSTRUMENTS) == 12
    assert len({i.symbol for i in INSTRUMENTS}) == 12
    assert len({i.source_ticker for i in INSTRUMENTS}) == 12


def test_todos_declaran_que_nombre_esperan():
    # Sin `expect_name` el guard no puede correr, que es como no tenerlo.
    assert all(i.expect_name for i in INSTRUMENTS)


# ── El parser de Yahoo ──────────────────────────────────────────────────────
def payload(stamps, closes):
    return {"chart": {"result": [{
        "timestamp": stamps,
        "indicators": {"quote": [{"close": closes, "open": closes,
                                  "high": closes, "low": closes,
                                  "volume": [1] * len(closes)}]},
    }]}}


def test_una_barra_sin_cierre_se_descarta():
    """Una barra sin close no es una barra: es un hueco que la fuente devuelve igual.

    Si entrara como dato, despues habria que adivinar si el None era real.
    """
    barras = YahooAdapter._parse("X", payload([1000, 2000, 3000], [1.0, None, 3.0]))
    assert [b.close for b in barras] == [1.0, 3.0]


def test_el_parser_convierte_a_utc():
    barras = YahooAdapter._parse("X", payload([0], [1.0]))
    assert barras[0].ts == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_un_error_de_la_fuente_es_SourceError():
    with pytest.raises(SourceError):
        YahooAdapter._parse("X", {"chart": {"error": "Not Found"}})


def test_una_respuesta_vacia_no_revienta():
    assert YahooAdapter._parse("X", {"chart": {"result": []}}) == []


def test_columnas_mas_cortas_que_los_timestamps_no_revientan():
    # Yahoo a veces devuelve arrays desparejos. Rellenar con None es mejor que un IndexError.
    p = {"chart": {"result": [{"timestamp": [1, 2, 3],
                               "indicators": {"quote": [{"close": [1.0]}]}}]}}
    assert len(YahooAdapter._parse("X", p)) == 1
