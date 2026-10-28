// Typed client for the FastAPI backend. Types mirror the Pydantic models.

export type Status =
  | "QL candidate" | "QL" | "excluded" | "disqualified" | "nurture" | "suppressed" | "needs review";

export interface QueueRow {
  person_id: string;
  name: string | null;
  company: string | null;
  channel: string | null;
  received_at: string | null;
  score: number | null;
  band: "A" | "B" | "nurture" | null;
  status: Status;
  owner: string | null;
  flagged: boolean;
}

export interface ConditionCheck {
  key: string;
  label: string;
  met: boolean | null;
  verified: boolean;
  evidence: string[];
}

export interface ScoreFactor { name: string; points: number; max_points: number; reason: string }

export interface Qualification {
  person_id: string;
  name: string | null;
  company: string | null;
  region: string | null;
  status: Status;
  exclusion: string | null;
  conditions: ConditionCheck[];
  gate_1_to_4_met: boolean;
  review_flags: string[];
  score: { total: number; band: string; factors: ScoreFactor[] } | null;
  owner: string | null;
  rationale: string;
  first_source: string | null;
}

export interface Message {
  id: string;
  channel: string;
  source: string | null;
  received_at: string;
  from_name: string | null;
  email: string | null;
  linkedin: string | null;
  subject: string | null;
  body: string;
}

export interface Extraction {
  language: string;
  intent: string;
  buyer_role: string | null;
  data_problem: { category: string; summary: string } | null;
  company_facts: { company_name: string | null; vertical: string | null;
                   employees: number | null; country: string | null };
  evidence: string[];
}

export interface ExtractionResult {
  message_id: string;
  extractor: string;
  status: "ok" | "failed";
  extraction: Extraction | null;
  error: string | null;
}

export interface Decision {
  id: string;
  decision: "accepted" | "rejected";
  decided_by: string | null;
  decided_at: string;
  note: string | null;
  origin: "seed" | "ui";
}

export interface Draft {
  text: string;
  language: string;
  generator: string;
  status: "pending_approval" | "approved";
  warnings: string[];
  created_at: string;
  approved_by: string | null;
  approved_at: string | null;
}

export interface LeadDetail {
  qualification: Qualification;
  messages: Message[];
  extractions: (ExtractionResult | null)[];
  decisions: Decision[];
  crm: { job_title: string | null; company_name: string | null; country: string | null } | null;
  draft: Draft | null;
}

export interface KpiRecord { person_id: string; name: string | null; company: string | null;
                             refs: string[]; note: string | null }
export interface KpiLine { key: string; label: string; actual: number | null;
                           target: number | null; records: KpiRecord[] }
export interface KpiPack {
  week_label: string;
  timezone: string;
  computed_at: string;
  acquisition: KpiLine[];
  qls_by_source: { source: string; feed: string; count: number | null; records: KpiRecord[] }[];
  expansion: KpiLine[];
  not_counted: KpiRecord[];
  data_notes: string[];
}

export interface AnswerCheck {
  answer_id: string; prompt_id: string; engine: string; mentioned: boolean;
  owned_citation: boolean; competitors: string[]; issues: string[]; answer_text: string;
  citations: string[];
}
export interface PromptGap {
  rank: number; prompt_id: string; prompt: string; cluster: string; priority: number;
  product: string | null; engines_mentioning: string[]; engines_citing_owned: string[];
  competitors: string[]; coverage: number; absence: number; competitor_share: number;
  product_fit: number; gap_score: number; issues: string[];
}
export interface Snapshot { answers: AnswerCheck[]; gaps: PromptGap[]; alerts: string[];
                            formula: string; known_competitors: string[] }
export interface Claim { text: string; sources: string[] }
export interface Brief {
  prompt_id: string; prompt: string; generator: string; created_at: string;
  status: "ok" | "needs edit";
  issues: { where: string; problem: string; blocked: boolean }[];
  body: { title: string; direct_answer: Claim; schema_org_type: string;
          sections: { heading: string; claims: Claim[] }[];
          faq: { question: string; answer: Claim[] }[] };
}

export class ApiError extends Error {
  constructor(public reasons: string[], public status: number) {
    super(reasons.join("; "));
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const reasons = Array.isArray(detail)
      ? detail.map((d: unknown) => (typeof d === "string" ? d : JSON.stringify(d)))
      : [`Request failed (${response.status})`];
    throw new ApiError(reasons, response.status);
  }
  return body as T;
}

const post = <T,>(path: string, data?: unknown) =>
  request<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data) });

export const api = {
  health: () => request<{ mode: string; extractor: string }>("/api/health"),
  leads: () => request<QueueRow[]>("/api/leads"),
  lead: (id: string) => request<LeadDetail>(`/api/leads/${encodeURIComponent(id)}`),
  submit: (data: Record<string, string | null>) =>
    post<{ message_id: string; person_id: string }>("/api/inbound", data),
  decide: (id: string, data: { decision: string; decided_by: string; decided_at: string | null;
                               note: string | null }) =>
    post(`/api/leads/${encodeURIComponent(id)}/decisions`, data),
  reanalyse: (id: string) => post(`/api/leads/${encodeURIComponent(id)}/reanalyse`),
  draft: (id: string) => post<{ draft: Draft }>(`/api/leads/${encodeURIComponent(id)}/draft`),
  approve: (id: string, approvedBy: string) =>
    post<{ draft: Draft; sent: false }>(`/api/leads/${encodeURIComponent(id)}/draft/approve`,
                                        { approved_by: approvedBy }),
  kpi: (week: string) => request<{ pack: KpiPack; markdown: string }>(`/api/kpi?week=${week}`),
  visibility: () => request<{ snapshot: Snapshot; briefs: Brief[] }>("/api/visibility"),
  brief: (promptId: string) => post<{ brief: Brief }>(`/api/visibility/briefs/${promptId}`),
};
