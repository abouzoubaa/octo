// Server-side API client (used inside routeLoader$, so the first paint already
// contains results — deep links from DMs open with the answer loaded).

export const API_BASE =
  (typeof process !== "undefined" && process.env.PUBLIC_API_BASE) || "http://localhost:8000";

export interface Evidence {
  source: string;
  text: string;
  start_ts: number | null;
}

export interface ProductRef {
  id: string;
  name: string;
}

export interface SearchResult {
  post_id: string;
  permalink: string | null;
  caption: string | null;
  post_type: string;
  posted_at: string | null;
  score: number;
  evidence: Evidence[];
  products: ProductRef[];
}

export interface Citation {
  n: number;
  post_id: string;
  permalink: string | null;
  quote: string;
}

export interface AnswerCard {
  state: "answered" | "no_strong_answer";
  text: string | null;
  citations: Citation[];
  confidence: number;
  answer_id: string | null;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
  answer: AnswerCard | null;
  deep_link: string;
}

export async function searchArchive(handle: string, q: string): Promise<SearchResponse | null> {
  const url = `${API_BASE}/api/${encodeURIComponent(handle)}/search?q=${encodeURIComponent(q)}`;
  const resp = await fetch(url);
  if (!resp.ok) return null;
  return resp.json();
}

export async function getAnswer(handle: string, answerId: string): Promise<AnswerCard | null> {
  const resp = await fetch(
    `${API_BASE}/api/${encodeURIComponent(handle)}/answer/${encodeURIComponent(answerId)}`
  );
  if (!resp.ok) return null;
  return resp.json();
}
