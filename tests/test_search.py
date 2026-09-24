from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from rb_wordstat import WordstatClient, WordstatParams
from rb_wordstat.core import services
from rb_wordstat.core.errors import AuthRequired, InvalidArguments, ProviderError
from rb_wordstat.core.models import ALL_FREQ_TYPES, FreqType, WordstatEntry, WordstatResult
from rb_wordstat.providers.base import WordstatProvider

from .test_cli import invoke, invoke_json


class FakeProvider(WordstatProvider):
    """Провайдер без HTTP: отвечает частотой по типу или падает с заданной ошибкой."""

    url = "unused"

    def __init__(self, name: str, fail: Exception | None = None) -> None:
        self.name = name  # ty: ignore[invalid-attribute-access]
        self.fail = fail
        self.calls: list[tuple[str, FreqType]] = []
        self._client = None

    def _params(self, query_sent: str, lr: int) -> dict:
        return {}

    def _api_error(self, data: dict):
        return None

    def _parse(self, data: dict):
        return 0, [], []

    async def fetch(self, query: str, freq_type: FreqType, lr: int) -> WordstatResult:
        self.calls.append((query, freq_type))
        if self.fail is not None:
            raise self.fail
        return result(query, freq_type, provider=self.name)


def result(query: str, freq_type: FreqType, *, provider: str = "fake", total: int = 100) -> WordstatResult:
    return WordstatResult(
        query=query,
        freq_type=freq_type,
        total_value=total,
        popular=[WordstatEntry(text=f"{query} купить", value=10)],
        associations=[WordstatEntry(text="ассоциация", value=5)],
        provider=provider,
    )


# --- WordstatClient ----------------------------------------------------------


def test_client_all_pairs_in_order_from_primary() -> None:
    primary, backup = FakeProvider("a"), FakeProvider("b")
    params = WordstatParams(query=["диван", "кресло"], freq=[FreqType.broad, FreqType.exact_ord])
    results = WordstatClient(providers=[primary, backup]).search_sync(params)
    assert [(r.query, r.freq_type, r.provider) for r in results] == [
        ("диван", FreqType.broad, "a"),
        ("диван", FreqType.exact_ord, "a"),
        ("кресло", FreqType.broad, "a"),
        ("кресло", FreqType.exact_ord, "a"),
    ]
    assert backup.calls == []


def test_client_falls_back_per_pair() -> None:
    primary = FakeProvider("a", fail=ProviderError("a", "лежит"))
    results = WordstatClient(providers=[primary, FakeProvider("b")]).search_sync(WordstatParams(query="диван"))
    assert [r.provider for r in results] == ["b"]


def test_client_single_error_as_is_and_combined_error() -> None:
    only = FakeProvider("a", fail=AuthRequired("a"))
    with pytest.raises(AuthRequired):
        WordstatClient(only).search_sync(WordstatParams(query="x"))

    both = [FakeProvider("a", fail=AuthRequired("a")), FakeProvider("b", fail=ProviderError("b", "лежит"))]
    with pytest.raises(ProviderError, match="все провайдеры отказали") as exc:
        WordstatClient(providers=both).search_sync(WordstatParams(query="x"))
    assert exc.value.to_dict()["provider"] == "a+b"


def test_client_by_name_without_credentials_falls_back() -> None:
    # xmlriver без доступов (conftest) → AuthRequired → следующий в очереди.
    results = WordstatClient(providers=["xmlriver", FakeProvider("b")]).search_sync(WordstatParams(query="x"))
    assert results[0].provider == "b"


def test_client_rejects_bad_chains() -> None:
    with pytest.raises(InvalidArguments):
        WordstatClient(providers=["nope"])
    with pytest.raises(ValueError, match="пуста"):
        WordstatClient(providers=[])
    with pytest.raises(ValueError, match="либо"):
        WordstatClient(FakeProvider("a"), providers=["xmlriver"])


# --- FreqType ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("freq_type", "expected", "label"),
    [
        (FreqType.broad, "купить диван", "базовая"),
        (FreqType.phrase, '"купить диван"', "фразовая"),
        (FreqType.exact, '"!купить !диван"', "точная"),
        (FreqType.exact_ord, '"[!купить !диван]"', "точная+порядок"),
    ],
)
def test_freq_operators(freq_type: FreqType, expected: str, label: str) -> None:
    assert freq_type.apply("купить диван") == expected
    assert freq_type.label == label


# --- services ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["broad"], [FreqType.broad]),
        (["broad", "phrase"], [FreqType.broad, FreqType.phrase]),
        (["broad, phrase,exact"], [FreqType.broad, FreqType.phrase, FreqType.exact]),
        (["broad,phrase", "exact"], [FreqType.broad, FreqType.phrase, FreqType.exact]),
        (["exact-ord"], [FreqType.exact_ord]),
        (["broad", "broad"], [FreqType.broad]),
        (["phrase,all"], ALL_FREQ_TYPES),
        ([], [FreqType.broad]),
    ],
)
def test_resolve_freq(values: list[str], expected: list[FreqType]) -> None:
    assert services.resolve_freq(values) == expected


def test_resolve_freq_invalid() -> None:
    with pytest.raises(InvalidArguments, match="wrong"):
        services.resolve_freq(["broad,wrong"])


def test_resolve_providers(tmp_path: Path) -> None:
    assert services.resolve_providers(" xmlstock , xmlriver", tmp_path) == ["xmlstock", "xmlriver"]
    assert services.resolve_providers(None, tmp_path) == ["xmlriver"]
    config = services.init_project(tmp_path, "demo")
    config.providers = ["xmlstock"]
    services.save_config(tmp_path, config)
    assert services.resolve_providers(None, tmp_path / "sub") == ["xmlstock"]


def test_search_rejects_bad_params() -> None:
    with pytest.raises(InvalidArguments):
        services.search(["x"], freq=[FreqType.broad], lr="москва", providers=["xmlriver"])  # ty: ignore[invalid-argument-type]


def test_csv_modes(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    results = [result("диван", FreqType.broad, total=100), result("диван", FreqType.phrase, total=40)]
    assert services.csv_mode_for("auto", [FreqType.broad, FreqType.phrase]) == "freq"
    assert services.csv_mode_for("auto", [FreqType.broad]) == "keywords"
    assert services.csv_mode_for("keywords", [FreqType.broad, FreqType.phrase]) == "keywords"

    freq_csv = tmp_path / "freq.csv"
    services.save_results(results, freq_csv, csv_mode="freq")
    rows = list(csv.reader(freq_csv.open(encoding="utf-8")))
    assert rows[0] == ["query", "freq_type", "freq_label", "operator", "total_value"]
    assert rows[2] == ["диван", "phrase", "фразовая", '"диван"', "40"]

    kw_csv = tmp_path / "kw.csv"
    services.save_results(results, kw_csv, csv_mode="keywords")
    rows = list(csv.reader(kw_csv.open(encoding="utf-8")))
    assert rows == [
        ["source_query", "type", "keyword", "value"],
        ["диван", "popular", "диван купить", "10"],
        ["диван", "assoc", "ассоциация", "5"],
    ]
    assert "пустым" not in caplog.text

    services.save_results(results[1:], kw_csv, csv_mode="keywords")
    assert "пустым" in caplog.text

    as_json = tmp_path / "out.json"
    services.save_results(results, as_json, csv_mode="freq")
    assert json.loads(as_json.read_text(encoding="utf-8"))[0]["total_value"] == 100


# --- command -------------------------------------------------------------------


@pytest.fixture
def fake_search(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake(queries, *, freq, lr, providers):
        calls.append({"queries": queries, "freq": freq, "lr": lr, "providers": providers})
        return [result(q, f) for q in queries for f in freq]

    monkeypatch.setattr(services, "search", fake)
    return calls


def test_search_json(fake_search: list[dict], tmp_path: Path) -> None:
    out = tmp_path / "freq.csv"
    code, payload = invoke_json(
        "--project", str(tmp_path), "search", "диван", "кресло", "-f", "broad,exact-ord", "--lr", "2",
        "-p", "xmlstock,xmlriver", "-o", str(out),
    )  # fmt: skip
    assert code == 0
    assert payload["count"] == 4
    assert payload["results"][1]["freq_type"] == "exact_ord"
    assert payload["saved_to"] == str(out)
    assert fake_search[0]["lr"] == 2
    assert fake_search[0]["providers"] == ["xmlstock", "xmlriver"]
    assert out.read_text(encoding="utf-8").startswith("query,freq_type")


def test_search_human_tables(fake_search: list[dict], tmp_path: Path) -> None:
    single = invoke("--project", str(tmp_path), "search", "диван")
    assert single.exit_code == 0
    assert "Частота (базовая)" in single.stdout
    assert "Похожие запросы" in single.stdout
    assert "Ассоциации" in single.stdout

    out = tmp_path / "kw.json"
    multi = invoke("--project", str(tmp_path), "search", "диван", "-f", "all", "--no-keywords", "-o", str(out))
    assert multi.exit_code == 0
    assert "точная+порядок" in multi.stdout
    assert "Похожие запросы" not in multi.stdout
    assert "Сохранено" in multi.stdout


def test_search_invalid_freq_is_exit_2(fake_search: list[dict]) -> None:
    code, payload = invoke_json("search", "диван", "-f", "wrong")
    assert code == 2
    assert payload["error"]["code"] == "INVALID_ARGUMENTS"
    assert fake_search == []


def test_search_without_credentials_is_exit_3(tmp_path: Path) -> None:
    code, payload = invoke_json("--project", str(tmp_path), "search", "диван")
    assert code == 3
    assert payload["error"]["code"] == "AUTH_REQUIRED"
    assert "auth login" in payload["error"]["action"]
