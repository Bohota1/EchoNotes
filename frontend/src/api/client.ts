/**
 * HTTP client. Every call goes through here so errors surface in one place.
 *
 * Errors carry a `spoken` field from the backend (`app/core/errors.py`): the sentence to announce.
 * A failure that only appears on screen is invisible to this app's users.
 */

export interface ApiError {
  status: number;
  message: string;
  spoken: string;
}

export const API_BASE = "/api/v1";

export async function apiGet<T>(_path: string): Promise<T> {
  throw new Error("not implemented");
}

export async function apiPost<T>(_path: string, _body?: unknown): Promise<T> {
  throw new Error("not implemented");
}

export async function apiPatch<T>(_path: string, _body: unknown): Promise<T> {
  throw new Error("not implemented");
}

export async function apiDelete(_path: string): Promise<void> {
  throw new Error("not implemented");
}

export async function apiUpload<T>(_path: string, _file: Blob, _fields?: Record<string, string>): Promise<T> {
  throw new Error("not implemented");
}
