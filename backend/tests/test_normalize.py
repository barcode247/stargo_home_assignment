import pytest

from stargo.domain.normalize import (
    NormalizationError,
    is_free_email_domain,
    normalize_country,
    normalize_domain,
    normalize_email,
    normalize_linkedin,
    normalize_vertical,
    region_for_country,
)


@pytest.mark.parametrize("raw, expected", [
    ("Anouk.DeVries@NordhavenFreight.com", "anouk.devries@nordhavenfreight.com"),
    ("  Greta.Holm@balticacargo.eu ", "greta.holm@balticacargo.eu"),
    ("", None),
    (None, None),
])
def test_normalize_email(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("raw", ["asdf@asdf", "no-at-sign.com", "a@b", "x@.com"])
def test_invalid_email_raises(raw):
    with pytest.raises(NormalizationError):
        normalize_email(raw)


@pytest.mark.parametrize("raw, expected", [
    ("www.NordhavenFreight.com", "nordhavenfreight.com"),
    ("nl.nordhavenfreight.com", "nordhavenfreight.com"),
    ("https://www.meridianhaulage.co.uk/about", "meridianhaulage.co.uk"),
    ("ops.lionport.com.sg", "lionport.com.sg"),
    ("noam@ashdodbay.co.il", "ashdodbay.co.il"),
    ("balticacargo.eu", "balticacargo.eu"),
])
def test_normalize_domain(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("raw", [
    "https://linkedin.com/in/TomBecker-Logistics",
    "https://www.linkedin.com/in/tombecker-logistics/",
    "linkedin.com/in/tombecker-logistics?trk=abc",
    "http://de.linkedin.com/in/TOMBECKER-LOGISTICS",
])
def test_linkedin_variants_collapse(raw):
    assert normalize_linkedin(raw) == "linkedin.com/in/tombecker-logistics"


@pytest.mark.parametrize("raw", ["https://example.com/in/someone",
                                 "https://linkedin.com/company/stargo"])
def test_linkedin_rejects_non_profiles(raw):
    with pytest.raises(NormalizationError):
        normalize_linkedin(raw)


def test_free_email_domains():
    assert is_free_email_domain("gmail.com")
    assert not is_free_email_domain("nordhavenfreight.com")


def test_country_and_region():
    assert normalize_country("Netherlands") == "NL"
    assert normalize_country("United Kingdom") == "GB"
    assert normalize_country("Atlantis") is None  # unknown stays unknown
    assert region_for_country("GB") == "UK"
    assert region_for_country(None) is None


def test_vertical_casing():
    assert normalize_vertical("Freight Forwarder") == "freight-forwarder"
