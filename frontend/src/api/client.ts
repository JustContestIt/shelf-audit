import { detailMessage, statusMessage } from '../lib/errors';
import type {
  CatalogItem,
  EvalResult,
  Health,
  PhotoStatus,
  QueuedResponse,
  ReportBrief,
  ReportFull,
  ReviewRequest,
  Store,
} from './types';

/** All API calls go through this prefix (Vite dev proxy / nginx strip it). */
export const API_BASE = '/api';

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export function isApiError(e: unknown, status?: number): e is ApiError {
  return e instanceof ApiError && (status === undefined || e.status === status);
}

export function errorText(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

type Query = Record<string, string | number | undefined | null>;

function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

async function request<T>(path: string, init: RequestInit & { query?: Query } = {}): Promise<T> {
  const { query, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(API_BASE + withQuery(path, query), rest);
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new ApiError(0, statusMessage(0));
  }
  const ctype = res.headers.get('content-type') || '';
  const isJson = ctype.includes('application/json');
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = isJson ? await res.json() : await res.text();
    } catch {
      body = null;
    }
    // nginx / proxy error pages are HTML — do not show them as the message
    if (typeof body === 'string' && /<html/i.test(body)) body = null;
    throw new ApiError(res.status, detailMessage(body, statusMessage(res.status)), body);
  }
  if (isJson) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

function json(body: unknown): RequestInit {
  return { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}

export interface UploadPhotoInput {
  file: File;
  store_code: string;
  store_name: string;
  route_code: string;
  agent_id: string;
}

export const api = {
  stores: (route_code?: string) => request<Store[]>('/stores', { query: { route_code } }),

  uploadPhoto(input: UploadPhotoInput): Promise<QueuedResponse> {
    const fd = new FormData();
    fd.append('file', input.file, input.file.name || 'photo.jpg');
    fd.append('store_code', input.store_code);
    fd.append('store_name', input.store_name);
    fd.append('route_code', input.route_code);
    fd.append('agent_id', input.agent_id);
    fd.append('source', 'web');
    return request<QueuedResponse>('/photos', { method: 'POST', body: fd });
  },

  status: (id: string, signal?: AbortSignal) =>
    request<PhotoStatus>(`/photos/${encodeURIComponent(id)}/status`, { signal }),

  reports: (query: { store_code?: string; status?: string; limit?: number } = {}) =>
    request<ReportBrief[]>('/reports', { query }),

  pendingReviews: (query: { store_code?: string; limit?: number } = {}) =>
    request<ReportBrief[]>('/reviews/pending', { query }),

  report: (id: string, signal?: AbortSignal) => request<ReportFull>(`/reports/${encodeURIComponent(id)}`, { signal }),

  photoUrl: (id: string, version?: string | null) =>
    `${API_BASE}/reports/${encodeURIComponent(id)}/photo${version ? `?v=${encodeURIComponent(version)}` : ''}`,

  review: (id: string, body: ReviewRequest) =>
    request<ReportFull>(`/reports/${encodeURIComponent(id)}/review`, json(body)),

  retake(id: string, file: File): Promise<QueuedResponse> {
    const fd = new FormData();
    fd.append('file', file, file.name || 'retake.jpg');
    return request<QueuedResponse>(`/reports/${encodeURIComponent(id)}/retake`, { method: 'POST', body: fd });
  },

  catalog: (query: { q?: string; brand?: string } = {}) => request<CatalogItem[]>('/catalog', { query }),

  evals: () => request<EvalResult[]>('/evals/latest'),

  mermaid: () => request<string>('/graph/mermaid'),

  health: () => request<Health>('/health'),
};
