"""Person resolution (ql_standard.md section 3).

People are merged only through shared normalized email or LinkedIn keys, using
union-find over CRM records and inbound messages. Name, city and company never
merge two people.
"""

from dataclasses import dataclass, field

from stargo.domain.models import CrmRecord, InboundMessage, identity_keys


@dataclass
class Person:
    person_id: str
    keys: set[str]
    crm: CrmRecord | None
    message_ids: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def primary_key(self) -> str:
        emails = sorted(k for k in self.keys if k.startswith("email:"))
        return emails[0] if emails else sorted(self.keys)[0]

    @property
    def email(self) -> str | None:
        if self.crm and self.crm.email:
            return self.crm.email
        emails = sorted(k for k in self.keys if k.startswith("email:"))
        return emails[0].removeprefix("email:") if emails else None


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, items: list[str]) -> None:
        self.find(items[0])  # registers single-key items too
        for other in items[1:]:
            a, b = self.find(items[0]), self.find(other)
            if a != b:
                self.parent[max(a, b)] = min(a, b)


@dataclass
class IdentityIndex:
    people: dict[str, Person]
    by_key: dict[str, str]
    by_message: dict[str, str]

    def person_for_key(self, key: str) -> Person | None:
        person_id = self.by_key.get(key)
        return self.people[person_id] if person_id else None

    def person_for_message(self, message_id: str) -> Person:
        return self.people[self.by_message[message_id]]


def resolve_people(crm: list[CrmRecord], messages: list[InboundMessage]) -> IdentityIndex:
    uf = _UnionFind()
    for record in crm:
        keys = identity_keys(record.email, record.linkedin)
        if keys:
            uf.union(keys)
    ordered = sorted(messages, key=lambda m: (m.received_at, m.id))
    for message in ordered:
        uf.union(message.identity_keys)

    groups: dict[str, set[str]] = {}
    for key in list(uf.parent):
        groups.setdefault(uf.find(key), set()).add(key)

    crm_by_root: dict[str, list[CrmRecord]] = {}
    for record in crm:
        keys = identity_keys(record.email, record.linkedin)
        if keys:
            crm_by_root.setdefault(uf.find(keys[0]), []).append(record)
    msgs_by_root: dict[str, list[InboundMessage]] = {}
    for message in ordered:
        msgs_by_root.setdefault(uf.find(message.identity_keys[0]), []).append(message)

    people: dict[str, Person] = {}
    by_key: dict[str, str] = {}
    by_message: dict[str, str] = {}
    for root, keys in groups.items():
        records = sorted(crm_by_root.get(root, []), key=lambda r: r.record_id)
        group_msgs = msgs_by_root.get(root, [])
        flags = []
        if len(records) > 1:
            flags.append(
                "identity conflict: keys link several CRM records "
                f"({', '.join(r.record_id for r in records)})"
            )
        person_id = records[0].record_id if records else f"P-{group_msgs[0].id}"
        person = Person(
            person_id=person_id,
            keys=keys,
            crm=records[0] if records else None,
            message_ids=[m.id for m in group_msgs],
            flags=flags,
        )
        people[person_id] = person
        for key in keys:
            by_key[key] = person_id
        for message in group_msgs:
            by_message[message.id] = person_id
    return IdentityIndex(people=people, by_key=by_key, by_message=by_message)
