"""Markdown export of a KPI pack (KPI_PACK.md)."""

from stargo.kpi.pack import KpiLine, KpiPack, KpiRecord


def _fmt(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def _who(record: KpiRecord) -> str:
    who = record.name or record.person_id
    if record.company:
        who += f" ({record.company})"
    refs = ", ".join(record.refs)
    note = f" — {record.note}" if record.note else ""
    return f"{who} [{refs}]{note}"


def _drill(lines: list[KpiLine]) -> list[str]:
    out = []
    for line in lines:
        if line.records:
            out.append(f"**{line.label}** ({_fmt(line.actual)})")
            out += [f"- {_who(r)}" for r in line.records]
            out.append("")
    return out


def render_markdown(pack: KpiPack) -> str:
    out = [
        f"# Weekly KPI pack: {pack.week_label}",
        "",
        f"Window: {pack.week_start} to {pack.week_end} (exclusive), {pack.timezone}. "
        f"Computed {pack.computed_at}.",
        "",
        "## Acquisition vs target",
        "",
        "| KPI | Actual | Target | Gap |",
        "|---|---:|---:|---:|",
    ]
    for line in pack.acquisition:
        gap = "" if line.actual is None or line.target is None else str(line.actual - line.target)
        out.append(f"| {line.label} | {_fmt(line.actual)} | {_fmt(line.target)} | {gap} |")
    out += ["", "## QLs by first-touch source", "", "| Source | Feed | QLs |", "|---|---|---:|"]
    for src in pack.qls_by_source:
        out.append(f"| {src.source} | {src.feed} | {_fmt(src.count)} |")
    out += ["", "## Expansion (existing customers, not in acquisition numbers)", "",
            "| KPI | Actual |", "|---|---:|"]
    out += [f"| {line.label} | {_fmt(line.actual)} |" for line in pack.expansion]
    out += ["", "## Records behind each number", ""]
    out += _drill(pack.acquisition) + _drill(pack.expansion)
    if pack.not_counted:
        out += ["## Considered but not counted", ""]
        out += [f"- {_who(r)}" for r in pack.not_counted]
        out.append("")
    if pack.data_notes:
        out += ["## Data notes", ""] + [f"- {n}" for n in pack.data_notes] + [""]
    return "\n".join(out)
