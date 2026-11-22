"""Several regions in one call: each region is its own paid request and its own row in the journal.

Rules these tests pin:
- `--lr 213,2` is two regions; a duplicate is asked once, garbage is an error and not a silent 213;
- every result says which region it belongs to, and the regions are asked in the order given;
- the journal keeps the regions apart (region is part of its key), so `--cache` answers each region from its own row.
"""

from __future__ import annotations

import pytest

from rb_wordstat.core import services
from rb_wordstat.core.cache import ResponseCache
from rb_wordstat.core.client import WordstatClient
from rb_wordstat.core.errors import InvalidArguments
from rb_wordstat.core.models import FreqType, WordstatParams, WordstatResult

from .test_search import FakeProvider


def test_a_list_of_regions_is_parsed_and_garbage_is_refused() -> None:
    assert services.parse_regions("213") == [213]
    assert services.parse_regions("213, 2 ,213") == [213, 2]  # a repeated region is one request
    with pytest.raises(InvalidArguments, match="не код региона"):
        services.parse_regions("213,москва")
    with pytest.raises(InvalidArguments, match="хотя бы один код"):
        services.parse_regions(" , ")


def test_the_regions_are_asked_one_by_one_in_the_order_given(monkeypatch) -> None:
    asked: list[int] = []

    class RecordingClient:
        """Stands in for `WordstatClient`: one call per region, the answer carries the region it belongs to."""

        def __init__(self, providers) -> None:
            self.providers = providers

        def search_sync(self, params: WordstatParams, **_):
            asked.append(params.lr)
            return [
                WordstatResult(
                    query=query,
                    region=params.lr,
                    freq_type=freq_type,
                    total_value=10,
                    popular=[],
                    associations=[],
                )
                for query in params.get_queries()
                for freq_type in params.freq
            ]

    monkeypatch.setattr(services, "WordstatClient", RecordingClient)

    found = services.search(["диван"], freq=[FreqType.broad], lr=[213, 2], providers=["fake"])

    assert asked == [213, 2]
    assert [row.region for row in found] == [213, 2]


def test_the_journal_keeps_regions_apart() -> None:
    journal = ResponseCache()
    journal.clear(None)
    for region in (213, 2):
        WordstatClient(providers=[FakeProvider("a")], cache=journal).search_sync(
            WordstatParams(query="диван", lr=region)
        )

    quiet = FakeProvider("a")
    cached = [
        WordstatClient(providers=[quiet], cache=journal).search_sync(
            WordstatParams(query="диван", lr=region), use_cache=True
        )[0]
        for region in (213, 2)
    ]

    assert [(row.region, row.from_cache) for row in cached] == [(213, True), (2, True)]
    assert quiet.calls == []  # neither region cost a request
