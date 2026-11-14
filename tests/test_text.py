from imoveis_radar.text import br_number, field_text, norm, parse_float, parse_money


def test_parse_money_brazilian_formats():
    assert parse_money("R$ 1.234.567,89") == 1234567.89
    assert parse_money("150.000") == 150000.0
    assert parse_money("150.00") == 150.0
    assert parse_money("") is None
    assert parse_money(None) is None
    assert parse_money("abc") is None
    assert parse_money("NaN") is None


def test_parse_float_and_norm():
    assert parse_float("45,5%") == 45.5
    assert norm("  São   Gonçalo ") == "SAO GONCALO"
    assert field_text("  RUA A  ") == "RUA A"


def test_br_number():
    assert br_number(1234.5) == "1.234,50"
    assert br_number(None) == ""
