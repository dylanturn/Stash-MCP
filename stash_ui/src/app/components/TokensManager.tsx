import React, { useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  ApiToken,
  IssuedToken,
  createToken,
  listTokens,
  revokeToken,
} from '../../api/auth';

const ALL_SCOPES = ['read', 'write'] as const;

export function TokensManager() {
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [issued, setIssued] = useState<IssuedToken | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  async function refresh() {
    try {
      const data = await listTokens(false);
      setTokens(data);
    } catch (err) {
      console.error(err);
      toast.error('Failed to load tokens');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function handleRevoke(t: ApiToken) {
    if (!window.confirm(`Revoke token "${t.name}"? MCP clients using it will start getting 401.`)) {
      return;
    }
    try {
      await revokeToken(t.id);
      toast.success('Token revoked');
      await refresh();
    } catch (err) {
      console.error(err);
      toast.error('Failed to revoke token');
    }
  }

  return (
    <div>
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="min-w-0">
          <h3
            className="text-base font-semibold mb-1"
            style={{ color: 'var(--stash-text-bright)' }}
          >
            API Tokens
          </h3>
          <p
            className="text-sm"
            style={{ color: 'var(--stash-text-secondary)' }}
          >
            Personal access tokens for MCP clients and scripts. Send as{' '}
            <code
              className="px-1.5 py-0.5 rounded text-xs"
              style={{ backgroundColor: 'var(--stash-bg-base)' }}
            >
              Authorization: Bearer …
            </code>{' '}
            against <code>/api/&lt;tenant&gt;/&lt;store&gt;/…</code> or{' '}
            <code>/mcp/&lt;tenant&gt;/&lt;store&gt;/</code>.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex-shrink-0 px-3 py-2 rounded-md text-sm whitespace-nowrap"
          style={{
            backgroundColor: 'var(--stash-accent)',
            color: 'var(--stash-bg-base)',
          }}
        >
          New token
        </button>
      </div>

      {issued && <IssuedTokenBanner issued={issued} onDismiss={() => setIssued(null)} />}

      {showCreate && (
        <CreateTokenForm
          onCancel={() => setShowCreate(false)}
          onCreated={(t) => {
            setIssued(t);
            setShowCreate(false);
            refresh();
          }}
        />
      )}

      {loading ? (
        <p style={{ color: 'var(--stash-text-secondary)' }}>Loading…</p>
      ) : tokens.length === 0 ? (
        <p style={{ color: 'var(--stash-text-secondary)' }}>
          No tokens yet. Click <em>New token</em> to mint one.
        </p>
      ) : (
        <div
          className="rounded-md overflow-hidden"
          style={{ border: '1px solid var(--stash-border)' }}
        >
          <table className="w-full text-sm">
            <thead>
              <tr
                style={{
                  backgroundColor: 'var(--stash-bg-base)',
                  color: 'var(--stash-text-secondary)',
                }}
              >
                <th className="px-3 py-2 text-left font-normal">Name</th>
                <th className="px-3 py-2 text-left font-normal">Scopes</th>
                <th className="px-3 py-2 text-left font-normal">Created</th>
                <th className="px-3 py-2 text-left font-normal">Last used</th>
                <th className="px-3 py-2 text-left font-normal">Expires</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {tokens.map((t) => (
                <tr
                  key={t.id}
                  className="border-t"
                  style={{ borderColor: 'var(--stash-border)' }}
                >
                  <td className="px-3 py-2">{t.name}</td>
                  <td className="px-3 py-2">{t.scopes.join(', ')}</td>
                  <td className="px-3 py-2">{formatDate(t.created_at)}</td>
                  <td className="px-3 py-2">{formatDate(t.last_used_at)}</td>
                  <td className="px-3 py-2">{formatDate(t.expires_at)}</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => handleRevoke(t)}
                      className="px-2 py-1 rounded border text-xs"
                      style={{
                        borderColor: 'var(--stash-border)',
                        color: 'var(--stash-text-secondary)',
                      }}
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function formatDate(s: string | null): string {
  if (!s) return '—';
  try {
    return new Date(s).toLocaleString();
  } catch {
    return s;
  }
}

function CreateTokenForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: (t: IssuedToken) => void;
}) {
  const [name, setName] = useState('');
  const [scopes, setScopes] = useState<Record<string, boolean>>({
    read: true,
    write: true,
  });
  const [expiresInDays, setExpiresInDays] = useState<number | ''>(90);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const selectedScopes = Object.entries(scopes)
      .filter(([, v]) => v)
      .map(([k]) => k);
    if (!name.trim() || selectedScopes.length === 0) return;
    setSubmitting(true);
    try {
      const issued = await createToken(
        name.trim(),
        selectedScopes,
        expiresInDays === '' ? null : Number(expiresInDays)
      );
      onCreated(issued);
    } catch (err) {
      console.error(err);
      toast.error('Failed to create token');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mb-6 p-4 rounded-md border space-y-3"
      style={{
        backgroundColor: 'var(--stash-bg-base)',
        borderColor: 'var(--stash-border)',
      }}
    >
      <div>
        <label
          className="block text-sm mb-1"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          Name
        </label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. laptop-claude-desktop"
          className="w-full px-3 py-2 rounded-md border text-sm"
          style={{
            backgroundColor: 'var(--stash-bg-surface)',
            borderColor: 'var(--stash-border)',
            color: 'var(--stash-text-primary)',
          }}
        />
      </div>

      <div>
        <span
          className="block text-sm mb-1"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          Scopes
        </span>
        <div className="flex gap-4">
          {ALL_SCOPES.map((s) => (
            <label key={s} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={!!scopes[s]}
                onChange={(e) =>
                  setScopes({ ...scopes, [s]: e.target.checked })
                }
              />
              {s}
            </label>
          ))}
        </div>
      </div>

      <div>
        <label
          className="block text-sm mb-1"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          Expires in (days) — blank for no expiry
        </label>
        <input
          type="number"
          min={1}
          max={3650}
          value={expiresInDays}
          onChange={(e) =>
            setExpiresInDays(
              e.target.value === '' ? '' : Math.max(1, Number(e.target.value))
            )
          }
          className="w-32 px-3 py-2 rounded-md border text-sm"
          style={{
            backgroundColor: 'var(--stash-bg-surface)',
            borderColor: 'var(--stash-border)',
            color: 'var(--stash-text-primary)',
          }}
        />
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting || !name.trim()}
          className="px-3 py-2 rounded-md text-sm disabled:opacity-50"
          style={{
            backgroundColor: 'var(--stash-accent)',
            color: 'var(--stash-bg-base)',
          }}
        >
          {submitting ? 'Creating…' : 'Create'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-3 py-2 rounded-md border text-sm"
          style={{
            borderColor: 'var(--stash-border)',
            color: 'var(--stash-text-secondary)',
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

function IssuedTokenBanner({
  issued,
  onDismiss,
}: {
  issued: IssuedToken;
  onDismiss: () => void;
}) {
  return (
    <div
      className="mb-6 p-4 rounded-md border"
      style={{
        backgroundColor: 'var(--stash-bg-base)',
        borderColor: 'var(--stash-accent)',
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <strong style={{ color: 'var(--stash-text-bright)' }}>
          Token created — copy it now.
        </strong>
        <button
          onClick={onDismiss}
          className="text-sm underline"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          Dismiss
        </button>
      </div>
      <p className="text-sm mb-2" style={{ color: 'var(--stash-text-secondary)' }}>
        You won't be able to see <em>{issued.name}</em> again after closing this banner.
      </p>
      <pre
        className="p-2 rounded text-xs overflow-x-auto select-all"
        style={{
          backgroundColor: 'var(--stash-bg-surface)',
          color: 'var(--stash-text-primary)',
        }}
      >
        {issued.token}
      </pre>
      <button
        onClick={() => {
          navigator.clipboard.writeText(issued.token);
          toast.success('Token copied');
        }}
        className="mt-2 px-3 py-1 rounded-md border text-xs"
        style={{
          borderColor: 'var(--stash-border)',
          color: 'var(--stash-text-primary)',
        }}
      >
        Copy
      </button>
    </div>
  );
}
