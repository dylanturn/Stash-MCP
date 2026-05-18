// Tenant-scoped store CRUD.
//
// Server-side surface lives under ``/tenants/{tenant_id}/stores/*`` (see
// ``stash_mcp/tenant_admin/routes.py``). All endpoints require admin role
// on the path's tenant; errors render as RFC 7807 Problem Details and
// surface through :class:`ProblemError` from ``./fetch``.

import { stashFetch } from './fetch';

export interface StoreInfo {
  id: string;
  tenant_id: string;
  slug: string;
  display_name: string;
  git_remote_url: string | null;
  git_branch: string;
  created_at: string;
}

export interface StoreCreate {
  slug: string;
  display_name: string;
  git_remote_url?: string | null;
  git_branch?: string;
}

export interface StoreUpdate {
  display_name?: string;
  git_remote_url?: string | null;
  git_branch?: string;
}

export async function createStore(
  tenantId: string,
  body: StoreCreate,
): Promise<StoreInfo> {
  const res = await stashFetch(`/tenants/${tenantId}/stores`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function updateStore(
  tenantId: string,
  slug: string,
  body: StoreUpdate,
): Promise<StoreInfo> {
  const res = await stashFetch(`/tenants/${tenantId}/stores/${slug}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

// Store deletion is irreversible (removes the on-disk repo). The
// backend requires ``?confirm=true`` so callers can't trigger it by
// mistake — callers should confirm the action with the user first.
export async function deleteStore(
  tenantId: string,
  slug: string,
): Promise<void> {
  await stashFetch(
    `/tenants/${tenantId}/stores/${slug}?confirm=true`,
    { method: 'DELETE' },
  );
}
