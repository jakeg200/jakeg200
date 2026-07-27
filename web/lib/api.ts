export const API = process.env.WARRANT_API ?? "http://localhost:8000";

export type Task = {
  id: string;
  domain: string;
  statement: string;
  notation: string;
  skill_ids: string[];
  difficulty_b: number;
};

export type Step = {
  index: number;
  raw_text: string;
  kind: string;
  status: "valid" | "invalid" | "unverifiable";
  tier: number;
  evidence: string;
  confidence: number | null;
  derives: boolean;
};

export type Diagnosis = {
  first_break_index: number | null;
  error_class: string;
  misconception_id: string | null;
  misconception_name: string | null;
  confidence: number;
  summary: string;
  derivation_present: boolean;
};

export type Attempt = {
  id: string;
  learner_id: string;
  task_id: string;
  statement: string;
  mode: string;
  mode_source: string;
  submitted_at: string;
  steps: Step[];
  diagnosis: Diagnosis;
  probe: string;
  coverage: Record<string, number>;
  claims_updated: { skill_id: string; level: string; n_unassisted: number }[];
};

export type Evidence = {
  attempt_id: string;
  task_id: string;
  statement: string;
  mode: string;
  submitted_at: string;
  href: string;
};

export type Claim = {
  skill_id: string;
  skill_code: string;
  skill_name: string;
  level: "secure" | "emerging" | "not_evidenced";
  unaided_demonstrations: number;
  assisted_demonstrations: number;
  last_evidence_at: string | null;
  evidence: Evidence[];
};

export type Record_ = {
  learner: { id: string; handle: string };
  claims: Claim[];
  generated_at: string;
  notes: string;
  mode_provenance: string;
  signature: { algorithm: string; issuer: string; key_kind: string; public_key: string };
};

export async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return (await response.json()) as T;
}
