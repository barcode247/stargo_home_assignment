"""Company accounts, grouped by normalized company domain.

CRM rows for one company carry messy, sometimes conflicting values. An account
takes the most common non-blank value per field and never fills a blank.
Customer and competitor status are account-level: anyone writing from a
customer's domain is expansion, anyone from a competitor's domain is excluded.
"""

from dataclasses import dataclass

from stargo.domain.models import CrmRecord
from stargo.domain.normalize import (
    email_domain,
    is_free_email_domain,
    most_common,
    region_for_country,
)


@dataclass(frozen=True)
class Account:
    domain: str
    name: str | None
    country: str | None
    vertical: str | None
    employees: int | None
    is_customer: bool
    is_competitor: bool
    owner: str | None
    record_ids: tuple[str, ...]

    @property
    def region(self) -> str | None:
        return region_for_country(self.country)


def _record_domain(record: CrmRecord) -> str | None:
    domain = record.company_domain or email_domain(record.email)
    return None if domain is None or is_free_email_domain(domain) else domain


def build_accounts(crm: list[CrmRecord]) -> dict[str, Account]:
    grouped: dict[str, list[CrmRecord]] = {}
    for record in crm:
        domain = _record_domain(record)
        if domain:
            grouped.setdefault(domain, []).append(record)
    accounts = {}
    for domain, rows in grouped.items():
        accounts[domain] = Account(
            domain=domain,
            name=most_common(r.company_name for r in rows),
            country=most_common(r.country for r in rows),
            vertical=most_common(r.vertical for r in rows),
            employees=most_common(r.employees for r in rows),
            is_customer=any(r.is_customer for r in rows),
            is_competitor=any(
                (r.lead_status or "").lower() == "competitor" or r.vertical == "software-vendor"
                for r in rows
            ),
            owner=most_common(r.owner for r in rows),
            record_ids=tuple(r.record_id for r in rows),
        )
    return accounts


def account_for(
    accounts: dict[str, Account], crm: CrmRecord | None, email: str | None
) -> Account | None:
    domain = _record_domain(crm) if crm else None
    if domain is None and email:
        domain = email_domain(email)
        if is_free_email_domain(domain):
            domain = None
    return accounts.get(domain) if domain else None
