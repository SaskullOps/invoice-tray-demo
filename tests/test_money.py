from decimal import Decimal

from invoice_tray.money import format_es, parse_es_numbers


def test_parse_spanish_and_plain_numbers():
    assert parse_es_numbers("Total: 1.234,56 € y 12.50 y 7 uds y 1234,5") == [
        Decimal("1234.56"),
        Decimal("12.50"),
        Decimal("7"),
        Decimal("1234.5"),
    ]


def test_format_es():
    assert format_es(Decimal("1234.5")) == "1.234,50"
