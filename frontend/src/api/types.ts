// Types of the shelf-audit FastAPI contract (derived from a real sample of
// /photos/{id}/status, /reports/{id} and /reports responses).
// Fields the backend may omit in some states are optional.

export type ReportStatus =
  | 'new'
  | 'detecting'
  | 'verifying'
  | 'awaiting_review'
  | 'approved'
  | 'edited'
  | 'rejected'
  | 'failed'
  | 'retake';

/** Known pipeline nodes (LangGraph). `reject` is the dead-end for a non-shelf / bad photo. */
export type GraphNode =
  | 'validate_input'
  | 'input_guard'
  | 'reject'
  | 'detect'
  | 'postprocess'
  | 'retrieve_refs'
  | 'verify_subtypes'
  | 'build_report'
  | 'human_review'
  | 'persist';

export interface Store {
  store_code: string;
  store_name: string;
  address: string;
  route_code: string;
}

export interface QueuedResponse {
  report_id: string;
  status: 'queued';
}

export interface ProgressEntry {
  node: GraphNode | string;
  /** ISO 8601 with offset */
  at: string;
  info: string;
}

export interface PhotoStatus {
  report_id: string;
  status: ReportStatus;
  running: boolean;
  /** absent when the graph state is gone (e.g. API restarted) and the record comes from the DB */
  waiting_review?: boolean;
  next?: string[];
  reject_reason: string | null;
  progress: ProgressEntry[];
  retakes?: number;
}

/** A row of /reports, /reviews/pending, and the head of /reports/{id}. */
export interface ReportBrief {
  report_id: string;
  created_at: string | null;
  updated_at: string | null;
  status: ReportStatus;
  store_code: string | null;
  store_name: string | null;
  route_code: string | null;
  agent_id: string | null;
  source: string | null;
  total_units: number | null;
  unknown_units: number | null;
  needs_review_units: number | null;
  overall_confidence: number | null;
  low_confidence: boolean | null;
  cost_usd: number | null;
  latency_s: number | null;
  prompt_version: string | null;
  models: string | null;
  reject_reason: string | null;
  flags: string[] | null;
}

export interface ReportRow {
  shelf_index: number;
  /** слева / центр / справа */
  position: string;
  brand: string;
  subtype: string | null;
  package_format: string | null;
  front_facing_count: number;
  needs_review: boolean;
  review_reason: string | null;
  group_keys: string[];
}

export interface ReportData {
  rows: ReportRow[];
  total_units: number;
  shelves: number;
  unknown_units: number;
  needs_review_units: number;
  foreign_units: number;
  overall_confidence: number | null;
  low_confidence: boolean;
  flags: string[];
  cost_usd: number;
  latency_s: number;
}

/** [ymin, xmin, ymax, xmax], normalised to 0..1000 */
export type Box2D = [number, number, number, number];

export interface DetectedBox {
  box_2d: Box2D;
  /** brand name, or "ЧУЖОЙ" for a competitor */
  label: string;
  subtype?: string | null;
  format?: string | null;
  shelf_index?: number | null;
  confidence?: number | null;
}

export interface PhotoMeta {
  width: number;
  height: number;
  sha256: string;
}

export interface RetrievalCandidate {
  canon_name: string;
  score: number;
  s_siglip?: number;
  s_hsv?: number;
  refs: string[];
}

export interface RetrievalGroup {
  brand: string;
  pass1: string | null;
  size: number;
  candidates: RetrievalCandidate[];
}

/** `_mode` / `_backend` plus "<shelf>.<group>" -> group */
export type Retrieval = {
  _mode?: 'topk' | 'all' | string;
  _backend?: string;
} & { [groupKey: string]: RetrievalGroup | string | undefined };

export interface Pass2Info {
  version: string;
  subtypes_changed: number;
  needs_review: number;
  shelves_applied?: number;
  shelves_total?: number;
  detail: unknown[];
  usage?: Record<string, number>;
  [extra: string]: unknown;
}

export interface LLMCall {
  pass: string;
  model: string;
  provider: string;
  latency_s: number;
  cost_usd: number | null;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  replayed: boolean;
  fallback_from: string[];
  at?: string;
}

export interface ReportBody {
  /** null/absent for rejected or crashed runs */
  report?: ReportData | null;
  boxes?: DetectedBox[];
  slivers?: DetectedBox[];
  photo?: PhotoMeta;
  retrieval?: Retrieval;
  pass2?: Pass2Info | null;
  llm_calls?: LLMCall[];
  progress?: ProgressEntry[];
  /** present for rejected photos */
  guard?: Record<string, unknown>;
}

export interface ReviewEdit {
  /** index in report.rows */
  row: number;
  subtype?: string | null;
  package_format?: string | null;
  front_facing_count?: number;
  delete?: true;
}

export interface ReviewRecord {
  action: 'approve' | 'edit' | 'retake';
  edits: ReviewEdit[];
  reviewer: string | null;
  comment: string | null;
  photo_path?: string | null;
  at: string;
}

export interface ReportFull extends ReportBrief {
  review: ReviewRecord | null;
  body: ReportBody;
}

export interface ReviewRequest {
  action: 'approve' | 'edit';
  edits: ReviewEdit[];
  reviewer?: string;
  comment?: string;
}

export interface CatalogItem {
  key: string;
  brand: string;
  canon_name: string;
  label_bg: string | null;
  refs: number;
}

export interface EvalFrame {
  frame_id: string;
  variant?: string | null;
  tier?: string | null;
  shelves?: number | null;
  units_gt?: number | null;
  units_pred?: number | null;
  count_exact_shelves?: number | null;
  subtype_errors?: number | null;
  contamination?: number | null;
  pack_errors?: number | null;
  cost_usd?: number | null;
  latency_s?: number | null;
  errors?: string[];
}

export interface EvalResult {
  file: string;
  name?: string;
  created_at?: string;
  mode?: 'replay' | 'live' | string;
  config?: Record<string, unknown>;
  summary?: Record<string, number | null>;
  per_frame?: EvalFrame[];
  slices?: Record<string, Record<string, number | null>>;
  notes?: string;
}

export interface Health {
  ok: boolean;
  version: string;
  llm_mode: string;
  gemini_key: boolean;
  db: boolean;
  retriever: string | null;
  refs_indexed: number;
  prompt: string;
  verify_prompt: string;
}
