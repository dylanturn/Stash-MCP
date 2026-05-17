import { stashFetch } from './fetch';

export interface TenantMembership {
  id: string;
  slug: string;
  display_name: string;
  role: 'admin' | 'member';
}

export interface Me {
  user_id: string;
  oidc_sub: string;
  email: string;
  display_name: string;
  auth_method: 'session' | 'oidc' | 'api_token';
  tenant_roles: Record<string, 'admin' | 'member'>;
  tenants: TenantMembership[];
}

export interface StoreSummary {
  id: string;
  slug: string;
  display_name: string;
  tenant_id: string;
  tenant_slug: string;
  tenant_display_name: string;
  role: 'admin' | 'member';
}

export interface McpServerBinding {
  id: string;
  tenant_slug: string;
  slug: string;
  name: string;
}

export interface ApiToken {
  id: string;
  name: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  mcp_server: McpServerBinding | null;
}

export interface IssuedToken extends Omit<ApiToken, 'last_used_at' | 'revoked_at'> {
  token: string;
}

export async function getMe(): Promise<Me> {
  const res = await stashFetch('/auth/me');
  if (!res.ok) throw new Error(`/auth/me failed: ${res.statusText}`);
  return res.json();
}

export async function getMyStores(): Promise<StoreSummary[]> {
  const res = await stashFetch('/auth/stores');
  if (!res.ok) throw new Error(`/auth/stores failed: ${res.statusText}`);
  return res.json();
}

export async function listTokens(
  includeRevoked = false
): Promise<ApiToken[]> {
  const q = includeRevoked ? '?include_revoked=true' : '';
  const res = await stashFetch(`/auth/tokens${q}`);
  if (!res.ok) throw new Error(`Failed to list tokens: ${res.statusText}`);
  return res.json();
}

export async function createToken(
  name: string,
  scopes: string[],
  expiresInDays: number | null,
  mcpServerId: string | null = null,
): Promise<IssuedToken> {
  const res = await stashFetch('/auth/tokens', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      scopes,
      expires_in_days: expiresInDays,
      mcp_server_id: mcpServerId,
    }),
  });
  if (!res.ok) throw new Error(`Failed to create token: ${res.statusText}`);
  return res.json();
}

export async function revokeToken(id: string): Promise<void> {
  const res = await stashFetch(`/auth/tokens/${id}`, { method: 'DELETE' });
  if (!res.ok && res.status !== 204) {
    throw new Error(`Failed to revoke token: ${res.statusText}`);
  }
}
