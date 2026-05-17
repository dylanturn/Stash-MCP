// REST client. Every operation is scoped to a (tenant, store) pair so the
// backend's per-store routing middleware can dispatch to the right
// FileSystem / GitBackend. Use `createApiClient(tenant, store)` to get a
// pre-bound client; the bare functions are exported for tests and
// non-component callers.

import { stashFetch } from './fetch';

export function apiBase(tenant: string, store: string): string {
  return `/api/${tenant}/${store}`;
}

export async function getTree(tenant: string, store: string) {
  const res = await stashFetch(`${apiBase(tenant, store)}/tree`);
  if (!res.ok) throw new Error(`Failed to get tree: ${res.statusText}`);
  return res.json();
}

/** Absolute URL for the raw bytes of a content file. Used by the UI to
 * render images, PDFs, and HTML artifacts directly via ``<img>``,
 * ``<iframe>``, etc. — the JSON content endpoint can't represent
 * non-UTF-8 bytes. */
export function rawUrl(tenant: string, store: string, path: string): string {
  const cleaned = path.replace(/^\/+/, '');
  return `${apiBase(tenant, store)}/raw/${cleaned
    .split('/')
    .map(encodeURIComponent)
    .join('/')}`;
}

export async function listContent(
  tenant: string,
  store: string,
  path: string = ''
) {
  const res = await stashFetch(
    `${apiBase(tenant, store)}/content${path ? `/${path}` : ''}`
  );
  if (!res.ok) throw new Error(`Failed to list content: ${res.statusText}`);
  return res.json();
}

export interface GetContentResult {
  content: any;
  etag: string | null;
}

export async function getContent(
  tenant: string,
  store: string,
  path: string
): Promise<GetContentResult> {
  const res = await stashFetch(`${apiBase(tenant, store)}/content/${path}`);
  if (!res.ok) throw new Error(`Failed to get content: ${res.statusText}`);
  return { content: await res.json(), etag: res.headers.get('ETag') };
}

export async function createContent(
  tenant: string,
  store: string,
  path: string,
  content: string
) {
  const res = await stashFetch(`${apiBase(tenant, store)}/content/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed to create content: ${res.statusText}`);
  return { body: await res.json(), etag: res.headers.get('ETag') };
}

export async function putContent(
  tenant: string,
  store: string,
  path: string,
  content: string,
  etag: string | null = null
) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (etag) headers['If-Match'] = etag;
  const res = await stashFetch(`${apiBase(tenant, store)}/content/${path}`, {
    method: 'PUT',
    headers,
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed to update content: ${res.statusText}`);
  return { body: await res.json(), etag: res.headers.get('ETag') };
}

export async function deleteContent(
  tenant: string,
  store: string,
  path: string
) {
  const res = await stashFetch(`${apiBase(tenant, store)}/content/${path}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Failed to delete content: ${res.statusText}`);
  return res.json();
}

export async function moveContent(
  tenant: string,
  store: string,
  path: string,
  destination: string
) {
  const res = await stashFetch(`${apiBase(tenant, store)}/content/${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ destination }),
  });
  if (!res.ok) throw new Error(`Failed to move content: ${res.statusText}`);
  return res.json();
}

// Search is intentionally 503 under auth-enabled deployments (a single
// shared index would leak across tenants). Kept here for completeness and
// for the legacy auth-disabled SPA path.
export async function searchContent(
  tenant: string,
  store: string,
  query: string
) {
  const res = await stashFetch(
    `${apiBase(tenant, store)}/search?q=${encodeURIComponent(query)}`
  );
  if (!res.ok) throw new Error(`Failed to search: ${res.statusText}`);
  return res.json();
}

export async function getHealth() {
  const res = await stashFetch('/api/health');
  if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`);
  return res.json();
}

export async function getGitOverview(
  tenant: string,
  store: string
): Promise<any | null> {
  try {
    const res = await stashFetch(`${apiBase(tenant, store)}/git/overview`, {
      redirectOn401: false,
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export interface ApiClient {
  tenant: string;
  store: string;
  getTree: () => Promise<any>;
  listContent: (path?: string) => Promise<any>;
  getContent: (path: string) => Promise<GetContentResult>;
  createContent: (path: string, content: string) => Promise<{ body: any; etag: string | null }>;
  putContent: (
    path: string,
    content: string,
    etag?: string | null
  ) => Promise<{ body: any; etag: string | null }>;
  deleteContent: (path: string) => Promise<any>;
  moveContent: (path: string, destination: string) => Promise<any>;
  getGitOverview: () => Promise<any | null>;
  rawUrl: (path: string) => string;
}

export function createApiClient(tenant: string, store: string): ApiClient {
  return {
    tenant,
    store,
    getTree: () => getTree(tenant, store),
    listContent: (path = '') => listContent(tenant, store, path),
    getContent: (path) => getContent(tenant, store, path),
    createContent: (path, content) => createContent(tenant, store, path, content),
    putContent: (path, content, etag = null) =>
      putContent(tenant, store, path, content, etag),
    deleteContent: (path) => deleteContent(tenant, store, path),
    moveContent: (path, destination) =>
      moveContent(tenant, store, path, destination),
    getGitOverview: () => getGitOverview(tenant, store),
    rawUrl: (path) => rawUrl(tenant, store, path),
  };
}
