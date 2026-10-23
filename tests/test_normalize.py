"""Tests of the normalisation functions of `core.normalize`: phrases, domains and URLs reduced to a stable key."""

from __future__ import annotations

import pytest

from rb_wordstat.core.normalize import norm_domain, norm_phrase, norm_url


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("  Купить  Ёлку\u00a0", "купить елку"),
        ("купить \t елку\n", "купить елку"),
        ("\uff33\uff25\uff2f аудит", "seo аудит"),  # NFKC: full-width letters
        ("", ""),
    ],
)
def test_norm_phrase(text: str, key: str) -> None:
    assert norm_phrase(text) == key


@pytest.mark.parametrize(
    "value",
    ["example.com", "WWW.Example.COM", "https://www.example.com/", "http://example.com:8080/a?b", "example.com."],
)
def test_norm_domain(value: str) -> None:
    assert norm_domain(value) == "example.com"


def test_norm_domain_idn() -> None:
    assert norm_domain("xn--e1afmkfd.xn--p1ai") == norm_domain("https://www.Пример.рф/") == "пример.рф"


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("https://www.example.com/", "example.com"),
        ("http://example.com", "example.com"),
        ("example.com/Catalog/", "example.com/Catalog"),
        ("https://www.example.com/Catalog/?p=2#top", "example.com/Catalog?p=2"),
        ("https://пример.рф/%D0%BA%D0%B0%D1%82%D0%B0%D0%BB%D0%BE%D0%B3/", "пример.рф/каталог"),
    ],
)
def test_norm_url(url: str, key: str) -> None:
    assert norm_url(url) == key
