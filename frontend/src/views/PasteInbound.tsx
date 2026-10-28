import { FormEvent, useState } from "react";
import { api } from "../api";
import { ErrorBox } from "./common";

const SOURCES = ["event-email", "paid", "historical-reactivation", "new-connection",
                 "warm-network", "organic/referral"];

const EMPTY = { from_name: "", from_email: "", linkedin_url: "", channel: "email_reply",
                subject: "", body: "", received_at: "", source: "" };

export default function PasteInbound() {
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const set = (key: keyof typeof EMPTY) =>
    (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const blankToNull = Object.fromEntries(
        Object.entries(form).map(([k, v]) => [k, v.trim() === "" ? null : v]));
      const result = await api.submit(blankToNull);
      window.location.hash = `#/leads/${encodeURIComponent(result.person_id)}`;
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h1>Paste a new inbound message</h1>
      <p className="muted small">
        It runs through the same pipeline as the seed data. Email or LinkedIn URL may be blank,
        but not both. Received time defaults to now; a time without an offset is Israel time.
      </p>
      <form className="panel" onSubmit={submit}>
        <div className="grid2">
          <div>
            <label htmlFor="from_name">Sender name</label>
            <input id="from_name" value={form.from_name} onChange={set("from_name")} />
          </div>
          <div>
            <label htmlFor="channel">Channel</label>
            <select id="channel" value={form.channel} onChange={set("channel")}>
              <option value="email_reply">Email reply</option>
              <option value="form_fill">Form fill</option>
              <option value="linkedin_dm">LinkedIn DM</option>
            </select>
          </div>
          <div>
            <label htmlFor="from_email">Email</label>
            <input id="from_email" value={form.from_email} onChange={set("from_email")}
                   inputMode="email" />
          </div>
          <div>
            <label htmlFor="linkedin_url">LinkedIn URL</label>
            <input id="linkedin_url" value={form.linkedin_url} onChange={set("linkedin_url")}
                   placeholder="linkedin.com/in/…" />
          </div>
          <div>
            <label htmlFor="received_at">Received at (optional, Israel time)</label>
            <input id="received_at" type="datetime-local" value={form.received_at}
                   onChange={set("received_at")} />
          </div>
          <div>
            <label htmlFor="source">Source (blank = not recorded)</label>
            <select id="source" value={form.source} onChange={set("source")}>
              <option value="">not recorded</option>
              {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
        <label htmlFor="subject">Subject (optional)</label>
        <input id="subject" value={form.subject} onChange={set("subject")} />
        <label htmlFor="body">Message text</label>
        <textarea id="body" value={form.body} onChange={set("body")} dir="auto" />
        <ErrorBox error={error} />
        <div className="row" style={{ marginTop: 10 }}>
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "Analysing…" : "Submit"}
          </button>
          <button type="button" onClick={() => setForm(EMPTY)} disabled={busy}>Clear</button>
        </div>
      </form>
    </>
  );
}
