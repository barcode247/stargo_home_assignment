import { useEffect, useState } from "react";
import { api, KpiLine, KpiPack, KpiRecord } from "../api";
import { israelTime } from "../format";
import { ErrorBox } from "./common";

function Records({ records }: { records: KpiRecord[] }) {
  if (records.length === 0) return <p className="muted small">No records.</p>;
  return (
    <table className="cards">
      <thead><tr><th>Person</th><th>Company</th><th>Records</th><th>Note</th></tr></thead>
      <tbody>
        {records.map((r, i) => (
          <tr key={`${r.person_id}-${i}`}>
            <td data-label="Person">
              {r.person_id === "unmatched" ? "unmatched" :
                <a href={`#/leads/${encodeURIComponent(r.person_id)}`}>{r.name ?? r.person_id}</a>}
            </td>
            <td data-label="Company">{r.company ?? "—"}</td>
            <td data-label="Records" className="mono">{r.refs.join(", ")}</td>
            <td data-label="Note" className="small">{r.note}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Card({ line, selected, onSelect }: { line: KpiLine; selected: boolean;
                                              onSelect: () => void }) {
  const pct = line.target && line.actual !== null ? Math.min(100, (line.actual / line.target) * 100) : 0;
  return (
    <button className={`kpi-card ${selected ? "selected" : ""}`} onClick={onSelect}>
      <div className="small muted">{line.label}</div>
      <div className="value">{line.actual ?? "unknown"}</div>
      {line.target !== null && (
        <>
          <div className="target">target {line.target} · gap {(line.actual ?? 0) - line.target}</div>
          <div className="bar"><span style={{ width: `${pct}%` }} /></div>
        </>
      )}
    </button>
  );
}

export default function KpiView() {
  const [week, setWeek] = useState("2026-10-04");
  const [pack, setPack] = useState<KpiPack | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState("qls");

  useEffect(() => {
    setError(null);
    api.kpi(week).then((r) => { setPack(r.pack); setMarkdown(r.markdown); })
      .catch((e) => { setError(e); setPack(null); });
  }, [week]);

  const allLines = pack ? [...pack.acquisition, ...pack.expansion] : [];
  const sourceSelected = selected.startsWith("source:");
  const drill = sourceSelected
    ? pack?.qls_by_source.find((s) => `source:${s.source}` === selected)?.records ?? []
    : allLines.find((l) => l.key === selected)?.records ?? [];

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Weekly KPI pack</h1>
        <label className="small">Week starting (Sunday){" "}
          <input type="date" value={week} onChange={(e) => setWeek(e.target.value)}
                 style={{ width: "auto" }} />
        </label>
      </div>
      <ErrorBox error={error} />
      {!pack && !error && <p className="muted">Loading…</p>}
      {pack && (
        <>
          <p className="muted small">
            {pack.week_label}, {pack.timezone}. Recomputed from stored decisions at{" "}
            {israelTime(pack.computed_at)}. Click a number to see the records behind it.
          </p>
          <h2>Acquisition vs target</h2>
          <div className="kpi-cards">
            {pack.acquisition.map((l) => (
              <Card key={l.key} line={l} selected={selected === l.key}
                    onSelect={() => setSelected(l.key)} />
            ))}
          </div>

          <div className="grid2" style={{ marginTop: 14 }}>
            <div className="panel">
              <h2 style={{ marginTop: 0 }}>QLs by first-touch source</h2>
              <table>
                <thead><tr><th>Source</th><th>Feed</th><th className="num">QLs</th></tr></thead>
                <tbody>
                  {pack.qls_by_source.map((s) => (
                    <tr key={s.source} className="clickable"
                        onClick={() => setSelected(`source:${s.source}`)}>
                      <td>{s.source}</td>
                      <td className="small muted">{s.feed}</td>
                      <td className="num"><strong>{s.count ?? "unknown"}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="panel">
              <h2 style={{ marginTop: 0 }}>Expansion (separate line)</h2>
              <table>
                <tbody>
                  {pack.expansion.map((l) => (
                    <tr key={l.key} className="clickable" onClick={() => setSelected(l.key)}>
                      <td>{l.label}</td><td className="num"><strong>{l.actual}</strong></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="panel">
            <h2 style={{ marginTop: 0 }}>
              Records behind: {sourceSelected ? selected.slice(7)
                : allLines.find((l) => l.key === selected)?.label}
            </h2>
            <Records records={drill} />
          </div>

          {pack.not_counted.length > 0 && (
            <div className="panel">
              <h2 style={{ marginTop: 0 }}>Considered but not counted</h2>
              <Records records={pack.not_counted} />
            </div>
          )}
          {pack.data_notes.length > 0 && (
            <div className="panel">
              <h2 style={{ marginTop: 0 }}>Data notes</h2>
              <ul className="small">{pack.data_notes.map((n) => <li key={n}>{n}</li>)}</ul>
            </div>
          )}
          <details className="panel">
            <summary>Markdown export</summary>
            <pre className="markdown">{markdown}</pre>
          </details>
        </>
      )}
    </>
  );
}
