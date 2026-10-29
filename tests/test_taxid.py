import pytest

from invoice_tray.taxid import TaxIdKind, make_cif, make_nie, make_nif, validate_tax_id


@pytest.mark.parametrize(
    ("value", "kind"),
    [
        ("12345678Z", TaxIdKind.NIF),
        ("12345678-z", TaxIdKind.NIF),
        ("X1234567L", TaxIdKind.NIE),
        ("B12345674", TaxIdKind.CIF),
        ("ESB12345674", TaxIdKind.CIF),
        ("B-1234567-4", TaxIdKind.CIF),
        ("P1234567D", TaxIdKind.CIF),
    ],
)
def test_valid_tax_ids(value, kind):
    result = validate_tax_id(value)
    assert result.valid, result.reason
    assert result.kind == kind


@pytest.mark.parametrize(
    "value",
    [
        "12345678A",  # wrong NIF letter
        "X1234567A",  # wrong NIE letter
        "B12345675",  # wrong CIF digit
        "P12345674",  # P entities need a control letter
        "B1234567",  # too short
        "",
        "HELLO",
    ],
)
def test_invalid_tax_ids(value):
    assert not validate_tax_id(value).valid


def test_generators_produce_valid_ids():
    assert validate_tax_id(make_cif("B", "0012345")).valid
    assert validate_tax_id(make_nif("00123456")).valid
    assert validate_tax_id(make_nie("Y", "0012345")).valid


def test_reason_is_spanish_and_mentions_digit():
    result = validate_tax_id("B12345675")
    assert "control" in result.reason
