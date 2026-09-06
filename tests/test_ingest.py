"""Ingestion tests. No network: the source is replaced by a double.

What is tested is the logic protecting the dataset, not that Yahoo responds.
"""

from datetime import datetime, timezone

import pytest

from feedstock.ingest import VerificationError, verify_name
from feedstock.instruments import BY_SYMBOL, INSTRUMENTS, TRAPS, Instrument
from feedstock.sources.base import Bar, SourceError
from feedstock.sources.yahoo import YahooAdapter


class FakeSource:
    name = "falsa"

    def __init__(self, nombre: str):
        self._nombre = nombre

    def display_name(self, ticker: str) -> str:
        return self._nombre

    def fetch(self, ticker, start, end, interval="1d"):
        return []


# ── The name guard: what stops the dataset being contaminated silently ───────
def test_the_correct_name_passes():
    inst = BY_SYMBOL["copper"]
    assert verify_name(FakeSource("Copper Dec 26"), inst) == "Copper Dec 26"


def test_zn_f_cannot_enter_as_zinc():
    """The real case. `ZN=F` returns the 10-year Treasury note, not zinc.

    Without this check it would enter as zinc, contaminate the metals dataset and there
    would be NO signal at all: a model trained on top would give plausible, false numbers.
    """
    fake_zinc = Instrument("zinc", "yahoo", "ZN=F", "Zinc", "metal")
    with pytest.raises(VerificationError, match="does not contain"):
        verify_name(FakeSource("10-Year T-Note Futures,Dec-2026"), fake_zinc)


def test_the_guard_message_says_nothing_was_ingested():
    with pytest.raises(VerificationError, match="NOTHING was ingested"):
        verify_name(FakeSource("Otra cosa"), BY_SYMBOL["gold"])


def test_the_comparison_is_case_insensitive():
    assert verify_name(FakeSource("COPPER DEC 26"), BY_SYMBOL["copper"])


def test_the_known_trap_is_documented():
    assert "ZN=F" in TRAPS and "zinc" in TRAPS["ZN=F"].lower()
    # And no instrument in the registry uses it.
    assert "ZN=F" not in {i.source_ticker for i in INSTRUMENTS}


# ── The registry ────────────────────────────────────────────────────────────
def test_there_are_twelve_instruments_with_unique_symbols():
    assert len(INSTRUMENTS) == 12
    assert len({i.symbol for i in INSTRUMENTS}) == 12
    assert len({i.source_ticker for i in INSTRUMENTS}) == 12


def test_all_declare_which_name_they_expect():
    # Without `expect_name` the guard cannot run, which is the same as not having it.
    assert all(i.expect_name for i in INSTRUMENTS)


# ── The Yahoo parser ────────────────────────────────────────────────────────
def payload(stamps, closes):
    return {"chart": {"result": [{
        "timestamp": stamps,
        "indicators": {"quote": [{"close": closes, "open": closes,
                                  "high": closes, "low": closes,
                                  "volume": [1] * len(closes)}]},
    }]}}


def test_a_bar_without_a_close_is_dropped():
    """A bar without a close is not a bar: it is a gap the source returns anyway.

    If it entered as data, someone would later have to guess whether the None was real.
    """
    bars = YahooAdapter._parse("X", payload([1000, 2000, 3000], [1.0, None, 3.0]))
    assert [b.close for b in bars] == [1.0, 3.0]


def test_the_parser_converts_to_utc():
    bars = YahooAdapter._parse("X", payload([0], [1.0]))
    assert bars[0].ts == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_a_source_error_is_a_SourceError():
    with pytest.raises(SourceError):
        YahooAdapter._parse("X", {"chart": {"error": "Not Found"}})


def test_an_empty_response_does_not_blow_up():
    assert YahooAdapter._parse("X", {"chart": {"result": []}}) == []


def test_columns_shorter_than_timestamps_do_not_blow_up():
    # Yahoo sometimes returns ragged arrays. Padding with None beats an IndexError.
    p = {"chart": {"result": [{"timestamp": [1, 2, 3],
                               "indicators": {"quote": [{"close": [1.0]}]}}]}}
    assert len(YahooAdapter._parse("X", p)) == 1
