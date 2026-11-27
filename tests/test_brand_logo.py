"""Background brand logo search against the real Postgres, with the web search faked."""

from uuid import uuid4

import httpx
import psycopg
import pytest

from agent import brand_logo
from api.config.config import DATABASE_URL

try:
    psycopg.connect(DATABASE_URL, connect_timeout=2).close()
except psycopg.OperationalError:
    pytest.skip("Postgres not running (docker compose up -d postgres)", allow_module_level=True)


@pytest.fixture
def brands(monkeypatch):
    """Creates test brands (newest, so picked first) and deletes them afterwards.
    Brands that aren't the test's raise a network error: they stay pending, untouched."""
    monkeypatch.setattr(brand_logo, "TAVILY_API_KEY", "key")
    prefix = f"Teste {uuid4()}"
    names: list[str] = []

    def make(*suffixes):
        with psycopg.connect(DATABASE_URL) as conn:
            for s in suffixes:
                names.append(f"{prefix} {s}")
                conn.execute("INSERT INTO brands (name, key) VALUES (%s, %s)", (names[-1], names[-1].lower()))
        return [f"{prefix} {s}" for s in suffixes]

    yield make
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("DELETE FROM brands WHERE name LIKE %s", (f"{prefix}%",))


def saved(name):
    with psycopg.connect(DATABASE_URL) as conn:
        return conn.execute("SELECT logo, searched_at IS NOT NULL FROM brands WHERE name = %s", (name,)).fetchone()


def test_saves_found_logo_and_marks_not_found_as_searched(brands, monkeypatch):
    found, missing = brands("A", "B")
    queries = []

    def search(query):
        queries.append(query)
        if query == f"{found} marca logo":
            return "https://x.com/a.png"
        if query == f"{missing} marca logo":
            return None
        raise httpx.ConnectError("not a test brand")

    monkeypatch.setattr(brand_logo, "search_logo", search)
    brand_logo.fill_brand_logos()
    assert saved(found) == ("https://x.com/a.png", True)
    assert saved(missing) == (None, True)  # searched: not tried again


def test_network_error_leaves_brand_pending_and_others_continue(brands, monkeypatch):
    broken, ok = brands("C", "D")

    def search(query):
        if query == f"{ok} marca logo":
            return "https://x.com/d.png"
        raise httpx.ConnectError("down")

    monkeypatch.setattr(brand_logo, "search_logo", search)
    brand_logo.fill_brand_logos()
    assert saved(broken) == (None, False)  # retried on the next round
    assert saved(ok) == ("https://x.com/d.png", True)


def test_searches_at_most_limit_brands(brands, monkeypatch):
    brands(*range(21))
    calls = []

    def search(query):
        calls.append(query)
        raise httpx.ConnectError("x")

    monkeypatch.setattr(brand_logo, "search_logo", search)
    brand_logo.fill_brand_logos()
    assert len(calls) == 20


def test_without_api_key_does_nothing(brands, monkeypatch):
    (name,) = brands("E")
    monkeypatch.setattr(brand_logo, "TAVILY_API_KEY", None)
    monkeypatch.setattr(brand_logo, "search_logo", lambda q: pytest.fail("searched without a key"))
    brand_logo.fill_brand_logos()
    assert saved(name) == (None, False)
