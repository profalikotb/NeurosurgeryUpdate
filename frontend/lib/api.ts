export const API = "/api/backend";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init || {};
  const res = await fetch(`${API}${path}`, {
    ...rest,
    headers: { ...(json !== undefined ? { "content-type": "application/json" } : {}), ...(rest.headers || {}) },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
    cache: "no-store",
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const pageImage = (docId: number, pageIndex: number, highlight?: string[], dpi?: number) => {
  const p = new URLSearchParams();
  if (highlight?.length) p.set("highlight", highlight.join("|"));
  if (dpi) p.set("dpi", String(dpi));
  const q = p.toString();
  return `${API}/documents/${docId}/pages/${pageIndex}/image${q ? `?${q}` : ""}`;
};
export const originalFile = (docId: number, pageIndex?: number) =>
  `${API}/documents/${docId}/file${pageIndex !== undefined ? `#page=${pageIndex + 1}` : ""}`;

export type Citation = {
  document_id: number;
  filename: string;
  title: string | null;
  authors: string | null;
  edition: string | null;
  year: number | null;
  publisher: string | null;
  isbn: string | null;
  metadata_verified: boolean;
  metadata_sources: Record<string, string>;
  chapter: string | null;
  section: string | null;
  page_index: number;
  pdf_page: number;
  printed_page: string | null;
  printed_page_source: "embedded" | "inferred" | null;
  reflowable: boolean;
  ocr: boolean;
  formatted: string;
};

export type Hit = {
  chunk_id: number;
  document_id: number;
  page_index: number;
  snippet: string;
  text: string;
  score: number | null;
  match: "all_terms" | "some_terms" | "semantic";
  citation: Citation;
};

export type SearchResult = {
  query: string;
  expanded_terms: string[][];
  highlight_terms: string[];
  semantic: boolean;
  semantic_error: string | null;
  coverage_note: string | null;
  hits: Hit[];
};

export type Doc = {
  id: number;
  folder_id: number | null;
  path: string;
  filename: string;
  ext: string;
  size: number;
  status: "pending" | "indexed" | "partial" | "duplicate" | "missing" | "error" | "ocr_needed" | "skipped";
  duplicate_of: number | null;
  possible_duplicate_of: number | null;
  title: string | null; title_src: string | null;
  authors: string | null; authors_src: string | null;
  edition: string | null; edition_src: string | null;
  year: number | null; year_src: string | null;
  publisher: string | null; publisher_src: string | null;
  isbn: string | null; isbn_src: string | null;
  metadata_verified: number;
  page_count: number | null;
  text_pages: number | null;
  ocr_pages: number | null;
  chunk_count: number | null;
  label_mode: string | null;
  has_toc: number;
  quality_score: number | null;
  quality_notes: string | null;
  error: string | null;
  added_at: string;
  indexed_at: string | null;
  toc?: { level: number; title: string; start_page: number; end_page: number }[];
  exists_on_disk?: boolean;
  source?: "local" | "gdrive";
  web_link?: string | null;
  uploaded?: boolean;
};

export type Folder = {
  id: number;
  path: string;
  label: string;
  enabled: number;
  added_at: string;
  last_scan_at: string | null;
  documents: number;
  indexed: number | null;
  errors: number | null;
  reachable: boolean;
  source?: "local" | "gdrive";
  web_link?: string | null;
};

export type Job = {
  id: number;
  kind: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: Record<string, number | string>;
  log: string;
};

export type Stats = {
  indexed_documents: number;
  verified_metadata: number;
  pages: number;
  chunks: number;
  ocr_pages: number;
  by_status: Record<string, number>;
  folders: number;
  last_scan_at: string | null;
  added_last_7_days: number;
  recent: { id: number; title: string | null; filename: string; indexed_at: string; page_count: number }[];
  questions_generated: number | null;
  saved_lectures: number | null;
  new_publications: number | null;
};

export type Status = {
  version: string;
  ocr_available: boolean;
  semantic_enabled: boolean;
  active_job: number | null;
  auto_indexing?: boolean;
  auto_indexing_interval?: number;
};

export type Publication = {
  id: number;
  pmid: string | null;
  pmcid: string | null;
  doi: string | null;
  source: string | null;
  title: string;
  authors: string | null;
  journal: string | null;
  pub_date: string | null;
  pub_types: string[];
  design: string | null;
  level: number | null;
  design_basis: string | null;
  is_oa: number;
  oa_pdf_url: string | null;
  license: string | null;
  abstract: string | null;
  cited_by: number | null;
  retracted: number;
  reviewed: number;
  saved: number;
  library_path: string | null;
  first_seen_at: string;
  topics?: string[];
  links: { pubmed: string | null; doi: string | null; pmc: string | null; europepmc: string | null };
};

export type Topic = {
  id: number;
  name: string;
  query: string;
  enabled: number;
  builtin: number;
  last_run_at: string | null;
  total: number;
  unreviewed: number | null;
  last_status: string | null;
  last_error: string | null;
};

export type SearchRun = {
  id: number;
  topic: string | null;
  query: string;
  window_from: string | null;
  window_to: string | null;
  source: string | null;
  started_at: string;
  finished_at: string | null;
  status: string;
  found: number | null;
  new: number | null;
  error: string | null;
};
