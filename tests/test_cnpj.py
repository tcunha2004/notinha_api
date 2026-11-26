from agent.extraction.nodes.extract.models import Store, format_cnpj


def test_formats_any_printed_variant():
    for printed in ("03821728000172", "03.821.728/0001-72", "03 821 728 0001 72"):
        assert format_cnpj(printed) == "03.821.728/0001-72"


def test_accepts_alphanumeric_cnpj():
    assert format_cnpj("12abc34501de35") == "12.ABC.345/01DE-35"


def test_misread_cnpj_becomes_none():
    assert format_cnpj("03.821.728/0001-73") is None  # wrong check digit
    assert format_cnpj("03.821.728/0001") is None  # cut off
    assert Store(id="03.821.728/0001-73").id is None
    assert Store(id="03821728000172").id == "03.821.728/0001-72"
