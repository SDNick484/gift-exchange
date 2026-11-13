import pytest

import common


@pytest.mark.parametrize("raw,cents", [("25", 2500), ("25.5", 2550), ("$25.00", 2500), ("1,299", 129900),
                                        (5000, 5000), ("", None), (None, None)])
def test_parse_cents_accepts(raw, cents): assert common.parse_cents(raw) == cents


@pytest.mark.parametrize("raw", ["abc", "-5", "NaN", "inf", "1.999", "1e5", 12.5, True, 100_000_001])
def test_parse_cents_rejects(raw):
    with pytest.raises(common.ApiError): common.parse_cents(raw)


@pytest.mark.parametrize("raw,out", [(" https://a.example.com/x ", "https://a.example.com/x"),
                                      ("amazon.example.com/hz/wishlist/ls/ABC123 ", "https://amazon.example.com/hz/wishlist/ls/ABC123"),
                                      ("", None)])
def test_clean_url_accepts(raw, out): assert common.clean_url(raw) == out


@pytest.mark.parametrize("raw", ["javascript:alert(1)", "see my list", "ftp://x.example.com", "x" * 2001, "//x.example.com"])
def test_clean_url_rejects(raw):
    with pytest.raises(common.ApiError): common.clean_url(raw)


def test_clean_url_edges():
    assert common.clean_url(None) is None
    assert common.clean_url("   ") is None
    assert common.clean_url("shop.example.com:8080/x") == "https://shop.example.com:8080/x"
    for raw in ("javascript:alert(1.5)", "https://a b.example.com", "https://", 5):
        with pytest.raises(common.ApiError): common.clean_url(raw)


def test_parse_cents_limits():
    assert common.parse_cents(100_000_000) == 100_000_000
    assert common.parse_cents("1,000,000.00") == 100_000_000
    for raw in ("1,23", "$", "1.", ".5", " ", [], {}, -1):
        if raw == " ":
            assert common.parse_cents(raw) is None
        else:
            with pytest.raises(common.ApiError): common.parse_cents(raw)


def test_text():
    assert common.text({"a": "  hi "}, "a", 10) == "hi"
    assert common.text({"a": "  "}, "a", 10) is None
    assert common.text({}, "a", 10) is None
    assert common.text({"a": None}, "a", 10) is None
    for data, required in (({}, True), ({"a": " "}, True), ({"a": 5}, False), ({"a": "x" * 11}, False)):
        with pytest.raises(common.ApiError) as e: common.text(data, "a", 10, required=required)
        assert e.value.status == 400


def test_clock():
    assert isinstance(common.now(), int)
    assert len(common.today()) == 10 and common.today()[4] == "-"
