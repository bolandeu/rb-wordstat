"""Стоимость запросов в `search --json`: цена по провайдеру из [prices] проекта и WORDSTAT_<PROVIDER>_PRICE."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rb_wordstat.core import opencli, services
from rb_wordstat.core.models import FreqType

from .test_cli import invoke, invoke_json
from .test_search import fake_search, result  # noqa: F401 — фикстура


@pytest.fixture(autouse=True)
def _no_price_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("WORDSTAT_XMLRIVER_PRICE", "WORDSTAT_XMLSTOCK_PRICE", "WORDSTAT_FAKE_PRICE"):
        monkeypatch.delenv(name, raising=False)


def _project(tmp_path: Path, prices: dict[str, float]) -> None:
    config = services.init_project(tmp_path, "demo")
    config.prices = prices
    services.save_config(tmp_path, config)


# --- цены ----------------------------------------------------------------------


def test_prices_from_config_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert services.resolve_prices(["xmlriver"], tmp_path) == {"xmlriver": None}

    _project(tmp_path, {"xmlriver": 0.5, "xmlstock": 0.25})
    assert services.resolve_prices(["xmlstock", "xmlriver"], tmp_path / "sub") == {"xmlstock": 0.25, "xmlriver": 0.5}

    monkeypatch.setenv("WORDSTAT_XMLRIVER_PRICE", "1.2")
    assert services.resolve_prices(["xmlriver"], tmp_path) == {"xmlriver": 1.2}


def test_price_from_env_only_and_bad_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("WORDSTAT_XMLSTOCK_PRICE", "0")
    assert services.resolve_prices(["xmlriver", "xmlstock"], tmp_path) == {"xmlriver": None, "xmlstock": 0.0}

    # Кривая цена не роняет уже оплаченный поиск: как не заданная, с предупреждением.
    monkeypatch.setenv("WORDSTAT_XMLSTOCK_PRICE", "дорого")
    assert services.resolve_prices(["xmlstock"], tmp_path) == {"xmlstock": None}
    assert "WORDSTAT_XMLSTOCK_PRICE" in caplog.text


def test_price_results(caplog: pytest.LogCaptureFixture) -> None:
    live = result("диван", FreqType.broad, provider="xmlriver")
    cached = result("диван", FreqType.phrase, provider="xmlriver").model_copy(update={"from_cache": True})
    rows, total = services.price_results([live, cached], {"xmlriver": 0.5})
    assert [(r["cost"], r["cost_currency"]) for r in rows] == [(0.5, "RUB"), (0, "RUB")]
    assert rows[0]["query"] == "диван" and rows[0]["total_value"] == 100
    assert total == 0.5
    assert caplog.text == ""

    other = result("кресло", FreqType.broad, provider="xmlstock")
    rows, total = services.price_results([live, other, other], {"xmlriver": 0.1, "xmlstock": None})
    assert [r["cost"] for r in rows] == [0.1, None, None]
    assert total is None  # часть стоимости неизвестна — итог тоже
    assert caplog.text.count("xmlstock") == 1  # одно предупреждение на провайдера
    assert "WORDSTAT_XMLSTOCK_PRICE" in caplog.text

    rows, total = services.price_results([cached], {"xmlriver": None})
    assert (rows[0]["cost"], total) == (0, 0)  # из журнала бесплатно, даже без цены


def test_price_total_has_no_float_noise() -> None:
    _rows, total = services.price_results([result("x", FreqType.broad, provider="a")] * 3, {"a": 0.1})
    assert total == 0.3


# --- команда -------------------------------------------------------------------


def test_search_json_has_cost(fake_search: list[dict], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    _project(tmp_path, {"fake": 0.4})
    code, payload = invoke_json("--project", str(tmp_path), "search", "диван", "кресло")
    assert code == 0
    assert [(r["cost"], r["cost_currency"]) for r in payload["results"]] == [(0.4, "RUB"), (0.4, "RUB")]
    assert payload["cost_total"] == 0.8

    monkeypatch.setenv("WORDSTAT_FAKE_PRICE", "0")
    code, payload = invoke_json("--project", str(tmp_path), "search", "диван")
    assert (payload["results"][0]["cost"], payload["cost_total"]) == (0, 0)


def test_search_without_price_warns(fake_search: list[dict], tmp_path: Path) -> None:  # noqa: F811
    run = invoke("--project", str(tmp_path), "search", "диван", "--json")
    assert run.exit_code == 0
    payload = json.loads(run.stdout)
    assert payload["results"][0]["cost"] is None
    assert payload["cost_total"] is None
    assert "WORDSTAT_FAKE_PRICE" in run.stderr  # CLI шлёт logging в stderr (configure_logging), не в caplog


def test_cost_documented() -> None:
    help_text = invoke("search", "--help", env={"COLUMNS": "200"}).stdout
    assert "cost_total" in help_text and "WORDSTAT_<PROVIDER>_PRICE" in help_text
    env = {entry["name"]: entry for entry in opencli.env_vars()}
    for provider in ("xmlriver", "xmlstock"):
        entry = env[f"WORDSTAT_{provider.upper()}_PRICE"]
        assert entry["purpose"] == "price" and entry["required"] is False
