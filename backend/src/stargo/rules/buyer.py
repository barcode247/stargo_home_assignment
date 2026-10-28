"""QL condition 2: is this a relevant buyer? Decided from the job title only."""

import re
from typing import Literal

Seniority = Literal["executive", "manager", "owner", "junior", "unknown"]

_JUNIOR = re.compile(
    r"\b(analyst|assistant|intern|student|coordinator|associate|specialist|representative"
    r"|clerk|team lead|trainee|junior)\b", re.IGNORECASE)
_OWNER = re.compile(r"\b(owner|founder|co-founder|cofounder)\b", re.IGNORECASE)
_GENERAL_EXEC = re.compile(
    r"\b(ceo|coo|cfo|cto|cio|cdo|cco|chief \w+ officer|president|managing director"
    r"|general manager)\b", re.IGNORECASE)
_EXEC = re.compile(r"\b(chief|vp|vice president|svp|evp|director|head)\b", re.IGNORECASE)
_MANAGER = re.compile(r"\b(manager|mgr)\b", re.IGNORECASE)
_BUYER_FUNCTION = re.compile(
    r"\b(pricing|price|operations|ops|procurement|purchasing|sourcing|commercial|sales|finance"
    r"|financial|treasury|digital|it|technology|transformation|innovation|logistics|transport"
    r"|transportation|supply chain|customs|trade|freight|station|business|revenue)\b",
    re.IGNORECASE)
_OTHER_FUNCTION = re.compile(
    r"\b(marketing|hr|human resources|people|talent|recruit\w*|partnerships?|customer service"
    r"|customer success|legal|communications|pr|design|brand|events?)\b", re.IGNORECASE)

OWNER_MAX_EMPLOYEES = 200


def seniority(title: str) -> Seniority:
    if _JUNIOR.search(title):
        return "junior"
    if _OWNER.search(title):
        return "owner"
    if _GENERAL_EXEC.search(title) or _EXEC.search(title):
        return "executive"
    if _MANAGER.search(title):
        return "manager"
    return "unknown"


def is_relevant_buyer(title: str | None, employees: int | None) -> tuple[bool | None, str]:
    """(met, reason). met is None when the title cannot decide it either way."""
    if not title:
        return None, "no job title on record or stated"
    level = seniority(title)
    if level == "junior":
        return False, f"'{title}' is below manager level"
    if level == "owner":
        if employees is None:
            return None, (f"'{title}' qualifies only under {OWNER_MAX_EMPLOYEES} employees; "
                          "size unknown")
        if employees < OWNER_MAX_EMPLOYEES:
            return True, f"'{title}' of a {employees}-employee company"
        return False, f"'{title}' but company has {employees} employees (owner rule is <200)"
    if level == "unknown":
        return None, f"cannot tell seniority from '{title}'"
    if _GENERAL_EXEC.search(title):
        return True, f"'{title}' is a general executive"
    if _OTHER_FUNCTION.search(title) and not _BUYER_FUNCTION.search(title):
        return False, (f"'{title}' does not own pricing, operations, procurement, commercial, "
                       "finance or digital")
    if _BUYER_FUNCTION.search(title):
        return True, f"'{title}' is {level}-level in a buying function"
    return None, f"'{title}' has no clear function"
