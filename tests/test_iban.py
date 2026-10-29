import pytest

from invoice_tray.iban import make_es_iban, validate_iban


@pytest.mark.parametrize(
    "value",
    ["ES9121000418450200051332", "ES91 2100 0418 4502 0005 1332", "GB82WEST12345698765432"],
)
def test_valid_ibans(value):
    assert validate_iban(value).valid


@pytest.mark.parametrize(
    "value",
    [
        "ES9221000418450200051332",
        "ES91 2100 0418 4502 0005 133",
        "XX00",
        "",
        "ES91210004184502000513A2",
    ],
)
def test_invalid_ibans(value):
    assert not validate_iban(value).valid


def test_generated_es_iban_is_valid_and_spanish_length():
    iban = make_es_iban("9999", "0001", "1234567890")
    assert len(iban) == 24
    assert validate_iban(iban).valid
