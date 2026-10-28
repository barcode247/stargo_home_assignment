import { useCallback, useEffect, useState } from "react";
import { api, ConditionCheck, ExtractionResult, LeadDetail as Detail, Message } from "../api";
import { channelLabel, israelNowLocalInput, israelTime } from "../format";
import { ErrorBox, ScoreBadge, StatusBadge } from "./common";

function Mark({ met }: { met: boolean | null }) {
  if (met === true) return <span className="mark yes" aria-label="met">✓</span>;
  if (met === false) return <span className="mark no" aria-label="not met">✗</span>;
  return <span className="mark unknown" aria-label="unknown">?</span>;
}

function Checklist({ conditions }: { conditions: ConditionCheck[] }) {
  return (
    <div>
      {conditions.map((c, i) => (
        <div className="check" key={c.key}>
          <Mark met={c.met} />
          <div>
            <strong>{i + 1}. {c.label}</strong>
            {!c.verified && c.met !== null && <span className="badge" style={{ marginLeft: 6 }}>unverified</span>}
            {c.evidence.map((e) => <div key={e} className="small muted">{e}</div>)}
          </div>
        </div>
      ))}
    </div>
  );
}

function MessageCard({ message, result }: { message: Message; result: ExtractionResult | null }) {
  const x = result?.extraction;
  return (
    <div className="panel">
      <div className="row small muted">
        <strong className="mono">{message.id}</strong>
        <span>{channelLabel[message.channel] ?? message.channel}</span>
        <span>{israelTime(message.received_at)}</span>
        <span>source: {message.source ?? "not recorded"}</span>
      </div>
      {message.subject && <p><strong>{message.subject}</strong></p>}
      <div className="message" dir="auto">{message.body}</div>
      <h3>Agent A extraction</h3>
      {!result && <p className="muted">Not analysed.</p>}
      {result?.status === "failed" && (
        <div className="notice">Analysis failed: {result.error}. A human decides.</div>
      )}
      {x && (
        <div className="small">
          <div className="row">
            <span>language <strong>{x.language}</strong></span>
            <span>intent <strong>{x.intent}</strong></span>
            <span>role <strong>{x.buyer_role ?? "—"}</strong></span>
          </div>
          <p>problem: <strong>{x.data_problem ? x.data_problem.category : "none stated"}</strong>
            {x.data_problem && <span className="muted"> · {x.data_problem.summary}</span>}</p>
          <p className="muted">stated facts: {Object.entries(x.company_facts)
            .filter(([, v]) => v !== null).map(([k, v]) => `${k}=${v}`).join(", ") || "none"}</p>
          {x.evidence.map((q) => <div key={q} className="quote" dir="auto">“{q}”</div>)}
          <div className="muted">by {result?.extractor}</div>
        </div>
      )}
    </div>
  );
}

function DecisionForm({ personId, onDone }: { personId: string; onDone: () => void }) {
  const [decidedBy, setDecidedBy] = useState("");
  const [decidedAt, setDecidedAt] = useState(israelNowLocalInput());
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (decision: "accepted" | "rejected") => {
    setBusy(true);
    setError(null);
    try {
      // The datetime-local value has no offset; the API reads it as Israel time.
      await api.decide(personId, { decision, decided_by: decidedBy, decided_at: decidedAt,
                                   note: note || null });
      setNote("");
      onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={(e) => e.preventDefault()}>
      <div className="grid2">
        <div>
          <label htmlFor="decided-by">Decided by</label>
          <input id="decided-by" value={decidedBy} onChange={(e) => setDecidedBy(e.target.value)}
                 placeholder="Your name" />
        </div>
        <div>
          <label htmlFor="decided-at">Decided at (Israel time)</label>
          <input id="decided-at" type="datetime-local" value={decidedAt}
                 onChange={(e) => setDecidedAt(e.target.value)} />
        </div>
      </div>
      <label htmlFor="note">Note</label>
      <input id="note" value={note} onChange={(e) => setNote(e.target.value)} />
      <ErrorBox error={error} />
      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" className="good" disabled={busy} onClick={() => submit("accepted")}>
          Accept
        </button>
        <button type="button" className="bad" disabled={busy} onClick={() => submit("rejected")}>
          Reject
        </button>
        <span className="small muted">Counts in the KPI week that contains this time.</span>
      </div>
    </form>
  );
}

function DraftPanel({ detail, onDone }: { detail: Detail; onDone: () => void }) {
  const [error, setError] = useState<unknown>(null);
  const [approver, setApprover] = useState("");
  const [busy, setBusy] = useState(false);
  const draft = detail.draft;
  const id = detail.qualification.person_id;

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel">
      <h2 style={{ marginTop: 0 }}>First-reply draft</h2>
      <p className="small muted">AI drafts, a human approves and sends it by hand. Nothing is sent.</p>
      {draft ? (
        <>
          <div className="message" dir="auto">{draft.text}</div>
          {draft.warnings.map((w) => <div key={w} className="notice small">{w}</div>)}
          <p className="small muted">
            {draft.generator} · {israelTime(draft.created_at)} ·{" "}
            {draft.status === "approved"
              ? `approved by ${draft.approved_by} ${israelTime(draft.approved_at)} (not sent)`
              : "pending approval"}
          </p>
          {draft.status !== "approved" && (
            <div className="row">
              <input value={approver} onChange={(e) => setApprover(e.target.value)}
                     placeholder="Approver name" style={{ maxWidth: 220 }} />
              <button className="good" disabled={busy || !approver.trim()}
                      onClick={() => run(() => api.approve(id, approver))}>Approve</button>
            </div>
          )}
          <div className="row" style={{ marginTop: 8 }}>
            <button disabled={busy} onClick={() => navigator.clipboard?.writeText(draft.text)}>
              Copy text
            </button>
            <button disabled={busy} onClick={() => run(() => api.draft(id))}>Regenerate</button>
          </div>
        </>
      ) : (
        <button className="primary" disabled={busy} onClick={() => run(() => api.draft(id))}>
          Draft a reply
        </button>
      )}
      <ErrorBox error={error} />
    </div>
  );
}

export default function LeadDetail({ personId }: { personId: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.lead(personId).then(setDetail).catch(setError);
  }, [personId]);
  useEffect(load, [load]);

  if (error) return <><a href="#/leads">← Leads</a><ErrorBox error={error} /></>;
  if (!detail) return <p className="muted">Loading…</p>;
  const q = detail.qualification;
  const failed = detail.extractions.some((x) => !x || x.status === "failed");

  return (
    <>
      <a href="#/leads">← Leads</a>
      <div className="row" style={{ marginTop: 8 }}>
        <h1 style={{ margin: 0 }}>{q.name ?? q.person_id}</h1>
        <StatusBadge status={q.status} />
        {q.score && <ScoreBadge score={q.score.total} band={q.score.band} />}
      </div>
      <p className="muted">
        {q.company ?? "company unknown"} · {q.region ?? "region unknown"} · owner{" "}
        <strong>{q.owner ?? "none"}</strong> · <span className="mono">{q.person_id}</span>
        {detail.crm?.job_title && <> · CRM title: {detail.crm.job_title}</>}
      </p>

      <div className="panel">
        <strong>Rationale.</strong> {q.rationale}
        {q.review_flags.map((f) => <div key={f} className="notice small">⚑ {f}</div>)}
        {failed && (
          <button style={{ marginTop: 8 }} disabled={busy} onClick={async () => {
            setBusy(true);
            try { await api.reanalyse(personId); load(); } catch (e) { setError(e); }
            finally { setBusy(false); }
          }}>Retry analysis</button>
        )}
      </div>

      <div className="grid2">
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>QL checklist</h2>
          <Checklist conditions={q.conditions} />
          {q.exclusion && <p className="small"><strong>Exclusion:</strong> {q.exclusion}</p>}
        </div>
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Priority score</h2>
          {q.score ? (
            <table>
              <tbody>
                {q.score.factors.map((f) => (
                  <tr key={f.name}>
                    <td>{f.name.replace("_", " ")}<div className="small muted">{f.reason}</div></td>
                    <td className="num">{f.points}/{f.max_points}</td>
                  </tr>
                ))}
                <tr><td><strong>Total</strong></td><td className="num"><strong>{q.score.total}</strong></td></tr>
              </tbody>
            </table>
          ) : <p className="muted">No score: no successful analysis.</p>}
          <p className="small muted">The score orders the queue. It never changes the status.</p>
        </div>
      </div>

      <div className="panel">
        <h2 style={{ marginTop: 0 }}>Sales decision</h2>
        {detail.decisions.length > 0 ? (
          <ul className="small">
            {detail.decisions.map((d) => (
              <li key={d.id}>
                <strong>{d.decision}</strong> by {d.decided_by ?? "unknown"} at{" "}
                {israelTime(d.decided_at)} <span className="mono muted">{d.id}</span>
                {d.note && <span className="muted"> · {d.note}</span>}
              </li>
            ))}
          </ul>
        ) : <p className="small muted">No decision yet.</p>}
        <DecisionForm personId={personId} onDone={load} />
      </div>

      <DraftPanel detail={detail} onDone={load} />

      <h2>Messages</h2>
      {detail.messages.length === 0 && <p className="muted">No inbound message on record.</p>}
      {detail.messages.map((m, i) => (
        <MessageCard key={m.id} message={m} result={detail.extractions[i]} />
      ))}
    </>
  );
}
