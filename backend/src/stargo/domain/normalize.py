"""Identity and firmographic normalization (ql_standard.md section 3).

Every function returns None for blank input and raises NormalizationError for
input that is present but malformed. Nothing here guesses a missing value.
"""

import re
from collections.abc import Iterable
from urllib.parse import unquote, urlsplit


class NormalizationError(ValueError):
    pass


EMAIL_RE = re.compile(r"^[a-z0-9._%+'-]+@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")

FREE_EMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com",
    "yahoo.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com",
    "gmx.de", "gmx.net", "web.de", "mail.com", "yandex.com", "zoho.com", "walla.co.il",
})

# Suffixes where the registrable domain has three labels (example.co.uk).
MULTI_PART_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "ltd.uk", "plc.uk",
    "com.sg", "edu.sg", "gov.sg", "org.sg",
    "co.il", "org.il", "ac.il", "net.il",
    "com.au", "co.nz", "co.jp", "com.hk", "co.za", "com.br", "com.cn", "co.in",
})

LINKEDIN_PATH_RE = re.compile(r"^/in/([^/]+)/?$")


def _blank(raw: str | None) -> bool:
    return raw is None or not str(raw).strip()


def normalize_email(raw: str | None) -> str | None:
    if _blank(raw):
        return None
    value = str(raw).strip().lower().removeprefix("mailto:")
    if not EMAIL_RE.match(value):
        raise NormalizationError("invalid email address")
    return value


def normalize_domain(raw: str | None) -> str | None:
    """Lowercase, strip scheme/path/www/subdomains, keep multi-part suffixes."""
    if _blank(raw):
        return None
    value = str(raw).strip().lower()
    if "@" in value:
        value = value.rsplit("@", 1)[1]
    if "://" not in value:
        value = "//" + value
    host = (urlsplit(value).hostname or "").strip(".")
    labels = [label for label in host.split(".") if label]
    if len(labels) < 2 or not all(re.fullmatch(r"[a-z0-9-]+", lb) for lb in labels):
        raise NormalizationError("invalid domain")
    keep = 3 if ".".join(labels[-2:]) in MULTI_PART_SUFFIXES else 2
    if len(labels) < keep:
        raise NormalizationError("invalid domain")
    return ".".join(labels[-keep:])


def email_domain(email: str | None) -> str | None:
    return normalize_domain(email.rsplit("@", 1)[1]) if email else None


def is_free_email_domain(domain: str | None) -> bool:
    return domain in FREE_EMAIL_DOMAINS


def normalize_linkedin(raw: str | None) -> str | None:
    """Canonical form: linkedin.com/in/<slug>, lowercase, no www, no trailing slash."""
    if _blank(raw):
        return None
    value = str(raw).strip()
    if "://" not in value:
        value = "https://" + value
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        raise NormalizationError("not a linkedin.com URL")
    match = LINKEDIN_PATH_RE.match(parts.path)
    if not match:
        raise NormalizationError("LinkedIn URL must be a profile URL (linkedin.com/in/...)")
    return f"linkedin.com/in/{unquote(match.group(1)).lower()}"


COUNTRY_ALIASES = {
    "nl": "NL", "netherlands": "NL", "the netherlands": "NL", "holland": "NL",
    "be": "BE", "belgium": "BE", "lu": "LU", "luxembourg": "LU",
    "uk": "GB", "gb": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB",
    "de": "DE", "germany": "DE", "deutschland": "DE", "at": "AT", "austria": "AT",
    "ch": "CH", "switzerland": "CH",
    "dk": "DK", "denmark": "DK", "se": "SE", "sweden": "SE", "no": "NO", "norway": "NO",
    "fi": "FI", "finland": "FI", "is": "IS", "iceland": "IS",
    "sg": "SG", "singapore": "SG",
    "us": "US", "usa": "US", "united states": "US", "united states of america": "US",
    "il": "IL", "israel": "IL",
    "au": "AU", "australia": "AU", "jp": "JP", "japan": "JP", "hk": "HK", "hong kong": "HK",
    "my": "MY", "malaysia": "MY", "in": "IN", "india": "IN", "cn": "CN", "china": "CN",
    "kr": "KR", "korea": "KR", "th": "TH", "thailand": "TH", "vn": "VN", "vietnam": "VN",
    "id": "ID", "indonesia": "ID", "ph": "PH", "philippines": "PH", "nz": "NZ",
    "new zealand": "NZ",
    "fr": "FR", "france": "FR", "es": "ES", "spain": "ES", "it": "IT", "italy": "IT",
    "pl": "PL", "poland": "PL", "ca": "CA", "canada": "CA",
}

REGION_BY_COUNTRY = {
    **dict.fromkeys(("NL", "BE", "LU"), "Benelux"),
    **dict.fromkeys(("DK", "SE", "NO", "FI", "IS"), "Nordics"),
    "GB": "UK",
    **dict.fromkeys(("DE", "AT", "CH"), "DACH"),
    "SG": "Singapore",
    "US": "United States",
    "IL": "Israel",
    **dict.fromkeys(("AU", "JP", "HK", "MY", "IN", "CN", "KR", "TH", "VN", "ID", "PH", "NZ"),
                    "APAC"),
}

ICP_REGIONS = frozenset({"Benelux", "Nordics", "UK", "DACH", "Singapore", "United States",
                         "Israel"})


def normalize_country(raw: str | None) -> str | None:
    """ISO-2 code, or None when blank or not recognised (unknown stays unknown)."""
    if _blank(raw):
        return None
    return COUNTRY_ALIASES.get(str(raw).strip().lower())


def region_for_country(country: str | None) -> str | None:
    return REGION_BY_COUNTRY.get(country) if country else None


VERTICAL_ALIASES = {
    "freight-forwarder": "freight-forwarder", "forwarder": "freight-forwarder",
    "freight-forwarding": "freight-forwarder",
    "carrier": "carrier", "3pl": "3pl", "third-party-logistics": "3pl",
    "trucking": "trucking", "haulage": "trucking",
    "air-cargo": "air-cargo", "ground-handling": "ground-handling",
    "customs-broker": "customs-broker", "customs-brokerage": "customs-broker",
    "shipper": "shipper", "trade-finance": "trade-finance",
    "software-vendor": "software-vendor", "investor": "investor",
}

ICP_VERTICALS = frozenset({
    "freight-forwarder", "carrier", "3pl", "trucking", "air-cargo", "ground-handling",
    "customs-broker", "shipper", "trade-finance",
})


def normalize_vertical(raw: str | None) -> str | None:
    if _blank(raw):
        return None
    slug = re.sub(r"[\s_]+", "-", str(raw).strip().lower())
    return VERTICAL_ALIASES.get(slug, slug)


def most_common(values: Iterable[object]) -> object | None:
    """Most frequent non-None value; ties go to the first seen."""
    counts: dict[object, int] = {}
    for value in values:
        if value is not None:
            counts[value] = counts.get(value, 0) + 1
    return max(counts, key=lambda v: counts[v]) if counts else None
