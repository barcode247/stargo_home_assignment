"""Priority score, 0 to 100 (ql_standard.md section 4).

Five additive factors, each explainable on its own. The score orders the queue;
it never changes the status, which only the QL gate decides.

| Factor        | Max | Rule                                                           |
|---------------|-----|----------------------------------------------------------------|
| intent        | 30  | pilot/demo 30, pricing 25, other 5, negative or excluded 0     |
| data problem  | 20  | specific pain with a number 20, specific pain 15, none 0       |
| buyer         | 20  | executive/owner 20, manager 14, unknown 5, not a buyer 0       |
| company fit   | 20  | ICP vertical 8 + size (200+: 7, 20-199: 5) + ICP region 5      |
| engagement    | 10  | 2+ substantive messages or channels 10, one 5                  |

Facts that are stated but not verified in the CRM earn 75% of their points.
"""

import re

from stargo.domain.normalize import ICP_REGIONS, ICP_VERTICALS
from stargo.domain.qualification import PriorityScore, ScoreFactor

UNVERIFIED_WEIGHT = 0.75
INTENT_POINTS = {"pilot": 30, "demo": 30, "pricing": 25, "other": 5}


def band_for(total: int) -> str:
    return "A" if total >= 70 else "B" if total >= 40 else "nurture"


def _weighted(points: float, verified: bool) -> int:
    return round(points if verified else points * UNVERIFIED_WEIGHT)


def priority_score(
    *,
    intent: str | None,
    problem_category: str | None,
    problem_text: str | None,
    buyer_met: bool | None,
    buyer_level: str | None,
    buyer_verified: bool,
    vertical: tuple[str | None, bool],
    employees: tuple[int | None, bool],
    region: tuple[str | None, bool],
    substantive_messages: int,
    channels: int,
) -> PriorityScore:
    factors = []

    intent_pts = INTENT_POINTS.get(intent or "", 0)
    factors.append(ScoreFactor(name="intent", points=intent_pts, max_points=30,
                               reason=f"strongest intent: {intent or 'none'}"))

    if problem_category:
        quantified = bool(problem_text and re.search(r"\d", problem_text))
        pts = 20 if quantified else 15
        reason = f"{problem_category.replace('_', ' ')}" + (" with volume stated" if quantified
                                                            else "")
    else:
        pts, reason = 0, "no specific data problem stated"
    factors.append(ScoreFactor(name="data_problem", points=pts, max_points=20, reason=reason))

    if buyer_met is True:
        raw = 20 if buyer_level in ("executive", "owner") else 14
        pts = _weighted(raw, buyer_verified)
        reason = f"{buyer_level} buyer" + ("" if buyer_verified else " (unverified)")
    elif buyer_met is None:
        pts, reason = 5, "buyer role unknown"
    else:
        pts, reason = 0, "not a relevant buyer"
    factors.append(ScoreFactor(name="buyer", points=pts, max_points=20, reason=reason))

    fit_pts, fit_notes = 0.0, []
    vert, vert_ok = vertical
    if vert in ICP_VERTICALS:
        fit_pts += _weighted(8, vert_ok)
        fit_notes.append(vert)
    size, size_ok = employees
    if size is not None and size >= 20:
        fit_pts += _weighted(7 if size >= 200 else 5, size_ok)
        fit_notes.append(f"{size} employees")
    reg, reg_ok = region
    if reg in ICP_REGIONS:
        fit_pts += _weighted(5, reg_ok)
        fit_notes.append(reg)
    factors.append(ScoreFactor(name="company_fit", points=int(fit_pts), max_points=20,
                               reason=", ".join(fit_notes) or "no ICP facts known"))

    touches = max(substantive_messages, channels)
    pts = 10 if touches >= 2 else 5 if touches == 1 else 0
    factors.append(ScoreFactor(name="engagement", points=pts, max_points=10,
                               reason=f"{substantive_messages} substantive message(s), "
                                      f"{channels} channel(s)"))

    total = min(100, sum(f.points for f in factors))
    return PriorityScore(total=total, band=band_for(total), factors=factors)
