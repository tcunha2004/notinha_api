from langgraph.graph import END

from agent.extraction.graph import (
    MAX_ATTEMPTS,
    InvoiceData,
    Item,
    find_errors,
    route_after_validation,
)


def make(**kw):
    base = dict(merchant="Mercado", date="2026-11-24", total=10.0, items=[Item(name="a", price=10.0)])
    return InvoiceData(**{**base, **kw})


def test_valid_data_has_no_errors():
    assert find_errors(make()) == []


def test_missing_fields_and_bad_sum_are_reported():
    assert find_errors(make(merchant=None, date=None, total=None))
    assert any("sum" in e for e in find_errors(make(total=99.0)))


def test_route_save_retry_or_give_up():
    assert route_after_validation({"errors": [], "attempts": 1}) == "save"
    assert route_after_validation({"errors": ["x"], "attempts": 1}) == "extract"
    assert route_after_validation({"errors": ["x"], "attempts": MAX_ATTEMPTS}) == END
