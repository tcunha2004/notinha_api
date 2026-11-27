import logging

import httpx
import psycopg

from agent.extraction.nodes.store_logo.node import search_logo
from api.config.config import DATABASE_URL, TAVILY_API_KEY

log = logging.getLogger(__name__)


def fill_brand_logos(limit: int = 20) -> None:
    """Searches the logo of brands never searched, newest first: the brands of the receipt just
    sent come first, and ones that keep failing don't block new ones.
    Runs after the upload response. Each round takes every pending brand, so a round lost to a
    restart is recovered by the next receipt."""
    # ponytail: rounds that overlap (receipts sent before the previous round ends) search the same
    # pending brands again; add a lock around the round (one API process) if the extra searches cost.
    if not TAVILY_API_KEY:
        return
    # autocommit: each brand is saved on its own, so a later failure doesn't undo it.
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        pending = conn.execute(
            "SELECT id, name FROM brands WHERE searched_at IS NULL ORDER BY created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        for brand_id, name in pending:
            try:
                logo = search_logo(f"{name} marca logo")
            except httpx.HTTPError, ValueError:
                log.exception("Brand logo search failed for %s", name)
                continue  # searched_at stays NULL: tried again next round
            conn.execute(
                "UPDATE brands SET logo = %s, searched_at = now() WHERE id = %s", (logo, brand_id)
            )
