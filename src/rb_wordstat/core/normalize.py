"""Natural keys shared between tools: one normalization, so `serp` and `wordstat` rows join.

Tools link their data in the shared database by these keys, not by each other's ids.
Store the key in its own indexed column next to the original text (`phrase` +
`phrase_key`) — the key loses information (case, ё, `www.`), the original must not.
A search phrase is keyed together with its region: the pair (`phrase_key`, `region`).

Changing what a function returns changes every stored key: that's a new `<tool>_v2_*`
view and a migration that recomputes the column, never an in-place edit.
"""

from __future__ import annotations

import contextlib
import unicodedata
from urllib.parse import unquote, urlsplit


def norm_phrase(text: str) -> str:
    """A search phrase as a key: NFKC, lower case, yo as ye (Ёлка → елка), whitespace collapsed to single spaces.

    `"  Купить  Ёлку\\t"` → `"купить елку"`.
    """
    # yo to ye; escaped, as the Cyrillic letters look like Latin ones to linters
    text = unicodedata.normalize("NFKC", text).lower().replace("\u0451", "\u0435")
    return " ".join(text.split())


def norm_domain(value: str) -> str:
    """A host as a key, from a bare domain or any URL: lower case, Unicode (not punycode), no `www.`, no port.

    `"https://WWW.Пример.рф:443/path"` and `"xn--e1afmkfd.xn--p1ai"` → `"пример.рф"`.
    """
    value = value.strip()
    host = urlsplit(value if "//" in value else f"//{value}").hostname or ""
    host = host.rstrip(".")
    with contextlib.suppress(UnicodeError):  # already Unicode, or not valid punycode: keep it as written
        host = host.encode("ascii").decode("idna")
    host = host.lower()
    return host.removeprefix("www.")


def norm_url(url: str) -> str:
    """A page URL as a key: `norm_domain` + the decoded path without the trailing slash, + the query.

    No scheme, no fragment; the path keeps its case (servers tell `/A` from `/a`).
    `"https://www.example.com/Catalog/?p=2#top"` → `"example.com/Catalog?p=2"`, the root page → `"example.com"`.
    """
    url = url.strip()
    parts = urlsplit(url if "//" in url else f"//{url}")
    key = norm_domain(url) + unquote(parts.path).rstrip("/")
    return f"{key}?{parts.query}" if parts.query else key
