import httpx

from agent.extraction.nodes.extract.models import ExtractionOutput, Store
from agent.extraction.nodes.store_logo import node as logo_node


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self.body = status, body
        self.is_success = status < 400

    def json(self):
        return self.body

    def raise_for_status(self):
        if not self.is_success:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]


def test_pick_logo_skips_photos_and_upgrades_http():
    images = [
        {"url": "https://x.com/fachada.jpg", "description": "Fachada da loja"},
        {"url": "data:image/png;base64,logo", "description": "Logo"},
        {"url": "http://x.com/a.png", "description": "EPA supermercados LOGO vermelho"},
    ]
    assert logo_node.pick_logo(images) == "https://x.com/a.png"
    assert logo_node.pick_logo(images[:2]) is None


def test_find_logo_searches_brand_name_from_cnpj(monkeypatch):
    queries = []
    monkeypatch.setattr(
        logo_node.httpx,
        "get",
        lambda url, **kw: FakeResponse(
            200 if url.endswith("/03821728000172") else 404, {"nome_fantasia": "EPA"}
        ),
    )

    def post(url, json, **kw):
        queries.append(json["query"])
        return FakeResponse(
            200, {"images": [{"url": "https://x.com/logo.png", "description": ""}]}
        )

    monkeypatch.setattr(logo_node.httpx, "post", post)
    assert (
        logo_node.find_logo("03.821.728/0001-72", "DMA DISTRIBUIDORA S/A")
        == "https://x.com/logo.png"
    )
    logo_node.find_logo("11.111.111/1111-11", "DMA DISTRIBUIDORA S/A")  # registry miss
    assert queries == ["EPA loja logo", "DMA DISTRIBUIDORA S/A loja logo"]


def test_node_never_blocks_on_failure_or_missing_cnpj(monkeypatch):
    monkeypatch.setattr(logo_node, "TAVILY_API_KEY", "key")
    no_cnpj = {"data": ExtractionOutput(store=Store(name="Mercado"))}
    assert logo_node.node_store_logo(no_cnpj) == {}  # type: ignore[arg-type]

    class NoLogoYet:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def execute(self, *a):
            return self

        def fetchone(self):
            return None

    monkeypatch.setattr(logo_node.psycopg, "connect", lambda *a, **kw: NoLogoYet())
    monkeypatch.setattr(
        logo_node.httpx,
        "get",
        lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("down")),
    )
    state = {
        "data": ExtractionOutput(store=Store(name="Mercado", id="03.821.728/0001-72"))
    }
    assert logo_node.node_store_logo(state) == {}  # type: ignore[arg-type]


def test_search_with_null_images_finds_nothing(monkeypatch):
    monkeypatch.setattr(logo_node.httpx, "post", lambda *a, **kw: FakeResponse(200, {"images": None}))
    assert logo_node.search_logo("Pilão marca logo") is None
