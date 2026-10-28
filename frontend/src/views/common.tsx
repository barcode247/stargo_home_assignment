import { ApiError, Status } from "../api";

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`badge status-${status.replace(/ /g, "-")}`}>{status}</span>;
}

export function ScoreBadge({ score, band }: { score: number | null; band: string | null }) {
  if (score === null) return <span className="badge">—</span>;
  return <span className={`badge ${band ?? ""}`} title={`Band ${band}`}>{score} · {band}</span>;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const reasons = error instanceof ApiError ? error.reasons : [String(error)];
  return (
    <div className="error" role="alert">
      {reasons.length === 1 ? reasons[0] : <ul>{reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
    </div>
  );
}
