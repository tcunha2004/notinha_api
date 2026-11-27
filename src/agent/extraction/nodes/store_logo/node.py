import logging
import re

import httpx
import psycopg

from agent.extraction.state import GraphState
from api.config.config import DATABASE_URL, TAVILY_API_KEY

log = logging.getLogger(__name__)


def pick_logo(images: list[dict]) -> str | None:
    """First image that Tavily describes (or names) as a logo. No logo is better than a wrong photo."""
    # ponytail: naive keyword match; let the LLM choose among the descriptions if it picks badly.
    for image in images:
        url = image.get("url") or ""
        text = f"{image.get('description') or ''} {url}".lower()
        if url.startswith(("https://", "http://")) and "logo" in text:
            return (
                "https://" + url.split("://", 1)[1]
            )  # the https app can't show http images
    return None


def brand_name(cnpj: str, fallback: str | None) -> str | None:
    """The receipt prints the legal name ("DMA DISTRIBUIDORA S/A"); the brand ("EPA") comes from the CNPJ registry."""
    digits = re.sub(r"\D", "", cnpj)
    r = httpx.get(f"https://brasilapi.com.br/api/cnpj/v1/{digits}", timeout=10)
    return (r.json().get("nome_fantasia") if r.is_success else None) or fallback


def search_logo(query: str) -> str | None:
    """Logo URL for the query, or None when the search has none. Raises httpx.HTTPError on failure."""
    r = httpx.post(
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
        json={
            "query": query,
            "include_images": True,
            "include_image_descriptions": True,
            "max_results": 5,
        },
        timeout=15,
    )
    r.raise_for_status()
    return pick_logo(r.json().get("images") or [])


def find_logo(cnpj: str, legal_name: str | None) -> str | None:
    name = brand_name(cnpj, legal_name)
    return search_logo(f"{name} loja logo") if name else None


def node_store_logo(state: GraphState) -> dict:
    store = state["data"].store  # type: ignore[typeddict-item]
    if not TAVILY_API_KEY or not store or not store.id:
        return {}

    # Search once per store: the next receipt from the same CNPJ reuses the saved logo.
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT logo FROM stores WHERE cnpj = %s", (store.id,)
        ).fetchone()
    if row and row[0]:
        return {}

    # The logo is a nice-to-have: a failed search must never block saving the receipt.
    try:
        logo = find_logo(store.id, store.name)
    except httpx.HTTPError, ValueError:
        log.exception("Store logo search failed for %s", store.id)
        return {}
    return {"store_logo": logo} if logo else {}
