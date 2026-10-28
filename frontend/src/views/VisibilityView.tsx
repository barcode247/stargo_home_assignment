import { useEffect, useState } from "react";
import { api, Brief, Claim, Snapshot } from "../api";
import { israelTime } from "../format";
import { ErrorBox } from "./common";

function ClaimText({ claim, blocked }: { claim: Claim; blocked: boolean }) {
  return (
    <span className={blocked ? "blocked" : undefined}>
      {claim.text}
      {claim.sources.map((s) => <span key={s} className="src">[{s}]</span>)}
    </span>
  );
}

function BriefView({ brief }: { brief: Brief }) {
  const { body } = brief;
  // Claims are struck through where the validator blocked something at that location.
  const isBlocked = (where: string) => brief.issues.some((i) => i.blocked && i.where === where);

  return (
    <div className="panel">
      <div className="row small muted">
        <span>{brief.generator}</span><span>{israelTime(brief.created_at)}</span>
        <span className={`badge ${brief.status === "ok" ? "A" : "B"}`}>{brief.status}</span>
        <span>schema.org: {body.schema_org_type}</span>
      </div>
      <h2>{body.title}</h2>
      <p><ClaimText claim={body.direct_answer} blocked={isBlocked("direct answer")} /></p>
      <p className="small muted">{body.direct_answer.text.split(/\s+/).length} words (contract: 40 to 60)</p>
      {body.sections.map((s) => (
        <div key={s.heading}>
          <h3>{s.heading}</h3>
          <ul>
            {s.claims.map((c) => (
              <li key={c.text}><ClaimText claim={c} blocked={isBlocked(`section '${s.heading}'`)} /></li>
            ))}
          </ul>
        </div>
      ))}
      <h3>FAQ</h3>
      {body.faq.map((f) => (
        <div key={f.question}>
          <p><strong>{f.question}</strong></p>
          {f.answer.map((c) => (
            <p key={c.text} className="small">
              <ClaimText claim={c} blocked={isBlocked(`FAQ '${f.question}'`)} />
            </p>
          ))}
        </div>
      ))}
      {brief.issues.length > 0 && (
        <>
          <h3>Validator findings</h3>
          <ul className="small">
            {brief.issues.map((i, n) => (
              <li key={n} className={i.blocked ? "blocked" : undefined} style={{ textDecoration: "none" }}>
                <strong>{i.blocked ? "Blocked" : "Flag"}</strong> · {i.where}: {i.problem}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

export default function VisibilityView() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [briefs, setBriefs] = useState<Record<string, Brief>>({});
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api.visibility().then((r) => {
      setSnapshot(r.snapshot);
      setBriefs(Object.fromEntries(r.briefs.map((b) => [b.prompt_id, b])));
    }).catch(setError);
  }, []);

  const generate = async (promptId: string) => {
    setBusy(promptId);
    setError(null);
    try {
      const { brief } = await api.brief(promptId);
      setBriefs((b) => ({ ...b, [promptId]: brief }));
      setOpen(promptId);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  };

  if (!snapshot) {
    return (
      <>
        <h1>AI visibility</h1>
        <ErrorBox error={error} />
        {!error && <p className="muted">Loading…</p>}
      </>
    );
  }
  const top = snapshot.gaps[0];
  const shown = open ?? (briefs[top.prompt_id] ? top.prompt_id : null);

  return (
    <>
      <h1>AI visibility snapshot</h1>
      <ErrorBox error={error} />
      {snapshot.alerts.length > 0 && (
        <div className="panel">
          <h2 style={{ marginTop: 0 }}>Brand accuracy alerts</h2>
          <ul className="small">{snapshot.alerts.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      )}

      <h2>Ranked gaps</h2>
      <table className="cards">
        <thead>
          <tr><th>#</th><th>Buyer prompt</th><th className="num">Gap</th><th>Stargo mentioned</th>
              <th>Owned citation</th><th>Competitors named</th><th></th></tr>
        </thead>
        <tbody>
          {snapshot.gaps.map((g) => (
            <tr key={g.prompt_id}>
              <td data-label="Rank">{g.rank}</td>
              <td data-label="Prompt">
                {g.prompt}
                <div className="small muted">{g.prompt_id} · {g.cluster} · priority {g.priority}
                  {g.product ? ` · ${g.product}` : " · no Stargo product"}</div>
                {g.issues.map((i) => <div key={i} className="small" style={{ color: "var(--bad)" }}>{i}</div>)}
              </td>
              <td data-label="Gap" className="num"><strong>{g.gap_score}</strong></td>
              <td data-label="Mentioned">{g.engines_mentioning.join(", ") || "none"}</td>
              <td data-label="Owned cite">{g.engines_citing_owned.join(", ") || "none"}</td>
              <td data-label="Competitors">{g.competitors.join(", ") || "—"}</td>
              <td data-label="Brief">
                {briefs[g.prompt_id] ? (
                  <button onClick={() => setOpen(g.prompt_id)}>View brief</button>
                ) : (
                  <button className={g.rank === 1 ? "primary" : undefined}
                          disabled={busy !== null} onClick={() => generate(g.prompt_id)}>
                    {busy === g.prompt_id ? "Writing…" : "Generate brief"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <details className="panel" style={{ marginTop: 14 }}>
        <summary>How the gap score works</summary>
        <pre className="markdown">{snapshot.formula}</pre>
      </details>

      {shown && briefs[shown] && (
        <>
          <h2>Content brief: {briefs[shown].prompt}</h2>
          <div className="row" style={{ marginBottom: 8 }}>
            <button disabled={busy !== null} onClick={() => generate(shown)}>Regenerate</button>
          </div>
          <BriefView brief={briefs[shown]} />
        </>
      )}

      <details className="panel">
        <summary>Per-answer detail ({snapshot.answers.length} captures)</summary>
        <table className="cards">
          <thead><tr><th>Answer</th><th>Mentioned</th><th>Owned</th><th>Text</th></tr></thead>
          <tbody>
            {snapshot.answers.map((a) => (
              <tr key={a.answer_id}>
                <td data-label="Answer" className="mono">{a.answer_id}</td>
                <td data-label="Mentioned">{a.mentioned ? "yes" : "no"}</td>
                <td data-label="Owned">{a.owned_citation ? "yes" : "no"}</td>
                <td data-label="Text" className="small">{a.answer_text}
                  <div className="muted">{a.citations.join(" · ")}</div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}
