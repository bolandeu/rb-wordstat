"""Device and depth: they change the answer, so they travel with the request and sit in the journal key.

Rules these tests pin:
- `WordstatParams` takes `device` as a comma list of known names and `limit` as 1..2000; anything else is an error,
  because a silently dropped device would answer a different question;
- the providers pass them to their own API (XMLStock: `device` and `groupby`; XML River: only `device` — the depth is
  an account setting there);
- two answers to the same phrase under different conditions are two rows, and `--cache` returns the one asked for.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from rb_wordstat.core.cache import ResponseCache, scope
from rb_wordstat.core.client import WordstatClient
from rb_wordstat.core.models import FreqType, WordstatParams
from rb_wordstat.providers.xmlriver import XmlRiverProvider
from rb_wordstat.providers.xmlstock import XmlStockProvider

from .test_search import FakeProvider

CREDENTIAL = {"user": "u", "token": "t"}


class RecordingProvider(FakeProvider):
    """A provider that records the conditions it was asked under and answers with a value of its own."""

    def __init__(self, name: str = "recording", total: int = 100) -> None:
        super().__init__(name)
        self.total = total
        self.seen: list[dict] = []

    async def fetch_raw(self, query, freq_type, lr, *, device=None, limit=None):  # ty: ignore[invalid-method-override]
        self.seen.append({"query": query, "device": device, "limit": limit})
        return {"total": self.total, "query": query}


def test_the_conditions_are_validated_not_silently_dropped() -> None:
    assert WordstatParams(query="q", device="desktop, phone").device == "desktop,phone"
    assert WordstatParams(query="q", device="desktop,desktop").device == "desktop"
    assert WordstatParams(query="q", limit=2000).limit == 2000
    with pytest.raises(ValidationError, match="device: tv"):
        WordstatParams(query="q", device="tv")
    with pytest.raises(ValidationError):
        WordstatParams(query="q", limit=0)
    with pytest.raises(ValidationError):
        WordstatParams(query="q", limit=2001)


def test_the_scope_of_an_answer_is_the_pair_of_conditions() -> None:
    assert scope(None, None) == ""  # the provider's own defaults, as the old rows were collected
    assert scope("desktop", None) == "desktop|"
    assert scope(None, 500) == "|500"
    assert scope("desktop", 500) == "desktop|500"


def test_xmlstock_sends_the_device_and_the_depth() -> None:
    params = XmlStockProvider(CREDENTIAL)._params("q", 213, device="desktop", limit=500)
    assert params["device"] == "desktop"
    assert params["groupby"] == 500
    assert XmlStockProvider(CREDENTIAL)._params("q", 213)["groupby"] == 200  # its documented default
    assert XmlStockProvider(CREDENTIAL)._params("q", 213)["device"] == "all"


def test_xmlriver_sends_the_device_and_no_depth() -> None:
    params = XmlRiverProvider(CREDENTIAL)._params("q", 213, device="phone", limit=500)
    assert params["device"] == "phone"
    assert "groupby" not in params  # the depth is an account setting there, not a parameter
    assert "device" not in XmlRiverProvider(CREDENTIAL)._params("q", 213)


def test_the_client_hands_the_conditions_to_the_provider() -> None:
    provider = RecordingProvider()
    WordstatClient(providers=[provider], cache=False).search_sync(WordstatParams(query="q", device="tablet", limit=300))
    assert provider.seen == [{"query": "q", "device": "tablet", "limit": 300}]


def test_two_answers_under_different_conditions_are_two_rows_and_the_cache_returns_the_asked_one() -> None:
    journal = ResponseCache()
    journal.clear(None)
    desktop = RecordingProvider(total=50)
    WordstatClient(providers=[desktop], cache=journal).search_sync(WordstatParams(query="диван", device="desktop"))
    everywhere = RecordingProvider(total=100)
    WordstatClient(providers=[everywhere], cache=journal).search_sync(WordstatParams(query="диван"))

    from_desktop = WordstatClient(providers=[RecordingProvider()], cache=journal).search_sync(
        WordstatParams(query="диван", device="desktop"), use_cache=True
    )
    from_all = WordstatClient(providers=[RecordingProvider()], cache=journal).search_sync(
        WordstatParams(query="диван"), use_cache=True
    )

    assert (from_desktop[0].total_value, from_desktop[0].from_cache) == (50, True)
    assert (from_all[0].total_value, from_all[0].from_cache) == (100, True)


def test_an_old_row_without_a_scope_still_answers_the_default_question() -> None:
    journal = ResponseCache()
    journal.clear(None)
    journal.put(
        provider="recording", freq_type=FreqType.broad.value, region=213, query="диван", total_value=77,
        data={"total": 77, "query": "диван"},
    )  # fmt: skip

    hit = WordstatClient(providers=[RecordingProvider()], cache=journal).search_sync(
        WordstatParams(query="диван"), use_cache=True
    )

    assert (hit[0].total_value, hit[0].from_cache) == (77, True)
    assert (
        journal.latest(provider="recording", freq_type="broad", region=213, query="диван", max_age=timedelta(0)) is None
    )
