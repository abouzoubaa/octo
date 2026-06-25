// Server-side admin/agent API client. The admin bearer token lives only on the
// server (never shipped to the browser) — these helpers run inside routeLoader$
// and routeAction$. Set ADMIN_API_TOKEN + PUBLIC_API_BASE in the web env.

const API_BASE =
  (typeof process !== "undefined" && process.env.PUBLIC_API_BASE) || "http://localhost:8000";
const ADMIN_TOKEN =
  (typeof process !== "undefined" && process.env.ADMIN_API_TOKEN) || "change-me";

function authHeaders(): Record<string, string> {
  return { Authorization: `Bearer ${ADMIN_TOKEN}`, "Content-Type": "application/json" };
}

export async function adminGet<T = unknown>(path: string): Promise<T | null> {
  try {
    const resp = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
    if (!resp.ok) return null;
    return (await resp.json()) as T;
  } catch {
    return null;
  }
}

export async function adminPost<T = unknown>(path: string, body?: unknown): Promise<T | null> {
  try {
    const resp = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: authHeaders(),
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!resp.ok) return null;
    return (await resp.json()) as T;
  } catch {
    return null;
  }
}

export interface CreatorRow {
  id: string;
  handle: string;
  display_name: string;
  status: string;
}

export interface DemandCard {
  id: string;
  label: string;
  search_count: number;
  comment_count: number;
  wow_change: number | null;
  recommendation: string | null;
  confidence: string | null;
  state: string;
  coverage: { gap?: boolean } | null;
  reconciliation?: {
    label: "well" | "partial" | "gap";
    strength: number;
    covered_permalink: string | null;
  } | null;
  opportunity_score: number | null;
  source_breakdown?: Record<string, number> | null;
  demand_segment?: string | null;
  integrity?: {
    unique_askers: number;
    manipulation_risk?: number | null;
    intent_class: string | null;
  };
}

export interface NorthStar {
  closed_loops: number;
  closed_loops_per_week: number;
  in_flight_loops: number;
  closed_breakdown?: { made: number; repromoted: number };
}

export interface ConnectorRow {
  platform: string;
  connected?: boolean;
  capabilities: string[];
  last_synced_at?: string | null;
}

export interface CanonicalRow {
  id: string;
  title: string;
  topic: string | null;
  variant_count: number;
  platforms: string[];
}

export interface ShiftOpportunity {
  canonical_id: string;
  title: string;
  source_platform: string;
  source_post_id: string;
  target_platform: string;
  covered_on: string[];
  has_demand: boolean;
}

export interface DmQueueItem {
  job_id: string;
  comment: string | null;
  public_reply: string | null;
  dm_text: string | null;
  deep_link: string | null;
  confidence: number | null;
}

export interface DraftRow {
  id: string;
  title: string;
  hooks: string[] | null;
  script: string | null;
  cta: string | null;
  status: string;
}

export interface InboxItem {
  kind: string;
  id: string;
  text: string | null;
  label: string;
  priority: number;
}

export const DEMAND_STATES = [
  "new",
  "idea",
  "drafting",
  "published",
  "loop_closed",
  "dismissed",
] as const;
