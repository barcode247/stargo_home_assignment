import { useEffect, useMemo, useState } from "react";
import { api, QueueRow } from "../api";
import { channelLabel, israelTime } from "../format";
import { ErrorBox, ScoreBadge, StatusBadge } from "./common";

type Sort = "received" | "score";

export default function LeadQueue() {
  const [rows, setRows] = useState<QueueRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [sort, setSort] = useState<Sort>("received");
  const [statusFilter, setStatusFilter] = useState("all");

  const [retrying, setRetrying] = useState(false);
  const [retryResult, setRetryResult] = useState<string | null>(null);

  const load = () => { api.leads().then(setRows).catch(setError); };
  useEffect(load, []);

  const failedCount = rows?.filter((r) => r.analysis_failed).length ?? 0;
  const retryFailed = async () => {
    setRetrying(true);
    setError(null);
    try {
      const r = await api.reanalyseFailed();
      setRetryResult(`Retried ${r.retried} message(s); ${r.still_failed} still failing.`);
      load();
    } catch (e) {
      setError(e);
    } finally {
      setRetrying(false);
    }
  };

  const visible = useMemo(() => {
    if (!rows) return [];
    const filtered = statusFilter === "all" ? rows : rows.filter((r) => r.status === statusFilter);
    return [...filtered].sort((a, b) =>
      sort === "score"
        ? (b.score ?? -1) - (a.score ?? -1)
        : (b.received_at ?? "").localeCompare(a.received_at ?? ""));
  }, [rows, sort, statusFilter]);

  const statuses = useMemo(() => Array.from(new Set(rows?.map((r) => r.status) ?? [])), [rows]);

  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Lead queue</h1>
        <div className="row small">
          <label>Sort{" "}
            <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}
                    style={{ width: "auto" }}>
              <option value="received">Newest first</option>
              <option value="score">Priority score</option>
            </select>
          </label>
          <label>Status{" "}
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
                    style={{ width: "auto" }}>
              <option value="all">All</option>
              {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        </div>
      </div>
      <ErrorBox error={error} />
      {failedCount > 0 && (
        <div className="notice row" style={{ justifyContent: "space-between" }}>
          <span>
            {failedCount} lead(s) have a failed analysis and wait in <strong>needs review</strong>.
            Fix the model settings (or add a key, for languages the rules cannot read), then
            retry.
          </span>
          <button disabled={retrying} onClick={retryFailed}>
            {retrying ? "Retrying…" : "Retry failed analyses"}
          </button>
        </div>
      )}
      {retryResult && <div className="success small">{retryResult}</div>}
      {!rows && !error && <p className="muted">Loading…</p>}
      {rows && (
        <table className="cards">
          <thead>
            <tr>
              <th>Name</th><th>Company</th><th>Channel</th><th>Received (Israel)</th>
              <th>Score</th><th>Status</th><th>Owner</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.person_id} className="clickable"
                  onClick={() => { window.location.hash = `#/leads/${encodeURIComponent(r.person_id)}`; }}>
                <td data-label="Name">
                  <a href={`#/leads/${encodeURIComponent(r.person_id)}`}>{r.name ?? r.person_id}</a>
                  {r.flagged && <span title="Flagged for review"> ⚑</span>}
                </td>
                <td data-label="Company">{r.company ?? <span className="muted">unknown</span>}</td>
                <td data-label="Channel">{r.channel ? channelLabel[r.channel] ?? r.channel : "—"}</td>
                <td data-label="Received">{israelTime(r.received_at)}</td>
                <td data-label="Score"><ScoreBadge score={r.score} band={r.band} /></td>
                <td data-label="Status"><StatusBadge status={r.status} /></td>
                <td data-label="Owner">{r.owner ?? <span className="muted">none</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
