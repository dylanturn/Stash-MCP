// MCP-server configuration CRUD (spec 02).
//
// Server-side surface lives under ``/tenants/{tenant_id}/mcp-servers/*``
// (see ``stash_mcp/tenant_admin/mcp_servers.py``). All endpoints require
// admin role on the path's tenant; errors render as RFC 7807 Problem
// Details and surface through :class:`ProblemError` from
// ``../api/fetch``.

import { stashFetch } from './fetch';

export interface Mount {
  id: string;
  store_id: string;
  store_slug: string;
  subpath: string;
  virtual_prefix: string;
  sort_order: number;
}

export interface ContentRoot {
  id: string;
  name: string;
  description: string | null;
  kind: 'simple' | 'virtual';
  sort_order: number;
  mounts: Mount[];
}

export interface McpServer {
  id: string;
  tenant_id: string;
  tenant_slug: string;
  slug: string;
  name: string;
  description: string | null;
  timeout_seconds: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  tools: string[];
  content_roots: ContentRoot[];
}

export interface MountInput {
  store_slug: string;
  subpath?: string;
  virtual_prefix?: string;
}

export interface ContentRootInput {
  name: string;
  description?: string | null;
  kind: 'simple' | 'virtual';
  mounts: MountInput[];
}

export interface McpServerCreate {
  slug: string;
  name: string;
  description?: string | null;
  timeout_seconds?: number;
  enabled?: boolean;
  tools?: string[];
  content_roots?: ContentRootInput[];
}

export interface McpServerUpdate {
  name?: string;
  description?: string | null;
  timeout_seconds?: number;
  enabled?: boolean;
  tools?: string[];
  content_roots?: ContentRootInput[];
}

export interface VisibleMcpServer {
  id: string;
  tenant_id: string;
  tenant_slug: string;
  slug: string;
  name: string;
}

export async function listMcpServers(tenantId: string): Promise<McpServer[]> {
  const res = await stashFetch(`/tenants/${tenantId}/mcp-servers`);
  return res.json();
}

export async function getMcpServer(
  tenantId: string,
  slug: string,
): Promise<McpServer> {
  const res = await stashFetch(`/tenants/${tenantId}/mcp-servers/${slug}`);
  return res.json();
}

export async function createMcpServer(
  tenantId: string,
  body: McpServerCreate,
): Promise<McpServer> {
  const res = await stashFetch(`/tenants/${tenantId}/mcp-servers`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function updateMcpServer(
  tenantId: string,
  slug: string,
  body: McpServerUpdate,
): Promise<McpServer> {
  const res = await stashFetch(`/tenants/${tenantId}/mcp-servers/${slug}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function deleteMcpServer(
  tenantId: string,
  slug: string,
): Promise<void> {
  await stashFetch(
    `/tenants/${tenantId}/mcp-servers/${slug}?confirm=true`,
    { method: 'DELETE' },
  );
}

export async function listVisibleMcpServers(): Promise<VisibleMcpServer[]> {
  const res = await stashFetch('/auth/visible-mcp-servers');
  return res.json();
}

// Catalog of MCP tool names, grouped by capability. Hard-coded here per
// spec 02 — the tool set changes rarely and avoiding a roundtrip on
// every modal open is worth the duplication.
//
// Keep in sync with ``REGISTERED_TOOL_NAMES`` in
// ``stash_mcp/mcp_server.py``.
export const TOOL_CATALOG = {
  read: [
    'read_content',
    'read_content_batch',
    'list_content',
    'inspect_content_structure',
    'inspect_content_structure_batch',
  ],
  write: [
    'create_content',
    'overwrite_content',
    'edit_content',
    'edit_content_batch',
    'delete_content',
    'move_content',
    'move_content_directory',
    'move_content_batch',
  ],
  search: ['search_content'],
  git: ['log_content', 'diff_content', 'blame_content'],
  transaction: [
    'start_content_transaction',
    'commit_content_transaction',
    'abort_content_transaction',
    'list_content_transactions',
  ],
} as const;

export type ToolGroup = keyof typeof TOOL_CATALOG;

// Tools that require a single-store config (matches
// ``_MULTI_STORE_DISALLOWED_TOOLS`` in ``stash_mcp/mcp_server.py``).
// The modal uses this to disable the relevant checkboxes when the
// user's content roots reference more than one store.
export const MULTI_STORE_DISALLOWED_TOOLS = new Set<string>([
  ...TOOL_CATALOG.git,
  ...TOOL_CATALOG.transaction,
]);
