import React, { useCallback, useEffect, useRef, useState } from 'react';
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
  // The modal that hosts this component can unmount while a request is
  // in flight (user closes the modal mid-fetch). Drop late results so we
  // don't call setState on an unmounted component.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = await listTokens(false);
      if (!mountedRef.current) return;
      setTokens(data);
    } catch (err) {
      if (!mountedRef.current) return;
      console.error(err);
      toast.error('Failed to load tokens');
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleRevoke(t: ApiToken) {
    if (!window.confirm(`Revoke token "${t.name}"? MCP clients using it will start getting 401.`)) {
      return;
    }
    try {
      await revokeToken(t.id);
      if (!mountedRef.current) return;
      toast.success('Token revoked');
      await refresh();
    } catch (err) {
      if (!mountedRef.current) return;
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
        <ThemedPrimaryButton
          onClick={() => setShowCreate(true)}
          className="flex-shrink-0 whitespace-nowrap"
        >
          New token
        </ThemedPrimaryButton>
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
                <th className="px-3 py-2 text-left font-normal text-xs uppercase tracking-wide">
                  Name
                </th>
                <th className="px-3 py-2 text-left font-normal text-xs uppercase tracking-wide">
                  Scopes
                </th>
                <th className="px-3 py-2 text-left font-normal text-xs uppercase tracking-wide whitespace-nowrap">
                  Created
                </th>
                <th className="px-3 py-2 text-left font-normal text-xs uppercase tracking-wide whitespace-nowrap">
                  Last used
                </th>
                <th className="px-3 py-2 text-left font-normal text-xs uppercase tracking-wide whitespace-nowrap">
                  Expires
                </th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {tokens.map((t, idx) => (
                <tr
                  key={t.id}
                  style={{
                    color: 'var(--stash-text-primary)',
                    borderTop:
                      idx === 0
                        ? 'none'
                        : '1px solid var(--stash-border)',
                  }}
                >
                  <td
                    className="px-3 py-2 align-middle"
                    style={{ color: 'var(--stash-text-bright)' }}
                  >
                    {t.name}
                  </td>
                  <td className="px-3 py-2 align-middle">
                    {t.scopes.join(', ')}
                  </td>
                  <td className="px-3 py-2 align-middle whitespace-nowrap">
                    {formatDate(t.created_at)}
                  </td>
                  <td className="px-3 py-2 align-middle whitespace-nowrap">
                    {formatDate(t.last_used_at)}
                  </td>
                  <td className="px-3 py-2 align-middle whitespace-nowrap">
                    {formatDate(t.expires_at)}
                  </td>
                  <td className="px-3 py-2 align-middle text-right">
                    <button
                      onClick={() => handleRevoke(t)}
                      className="px-2 py-1 rounded-md text-xs transition-all duration-150"
                      style={{
                        backgroundColor: 'transparent',
                        color: 'var(--stash-text-primary)',
                        border: '1px solid var(--stash-border)',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor =
                          'var(--stash-bg-hover)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'transparent';
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
    return new Date(s).toLocaleString(undefined, {
      dateStyle: 'short',
      timeStyle: 'short',
    });
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
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

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
      if (!mountedRef.current) return;
      onCreated(issued);
    } catch (err) {
      if (!mountedRef.current) return;
      console.error(err);
      toast.error('Failed to create token');
    } finally {
      if (mountedRef.current) setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mb-6 p-4 rounded-md border space-y-4"
      style={{
        backgroundColor: 'var(--stash-bg-base)',
        borderColor: 'var(--stash-border)',
      }}
    >
      <div>
        <label
          className="block text-sm mb-2"
          style={{ color: 'var(--stash-text-primary)' }}
        >
          Name
        </label>
        <ThemedInput
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. laptop-claude-desktop"
        />
      </div>

      <div>
        <span
          className="block text-sm mb-2"
          style={{ color: 'var(--stash-text-primary)' }}
        >
          Scopes
        </span>
        <div className="flex gap-5">
          {ALL_SCOPES.map((s) => (
            <label
              key={s}
              className="flex items-center gap-2 text-sm cursor-pointer"
              style={{ color: 'var(--stash-text-primary)' }}
            >
              <input
                type="checkbox"
                checked={!!scopes[s]}
                onChange={(e) =>
                  setScopes({ ...scopes, [s]: e.target.checked })
                }
                className="w-4 h-4 cursor-pointer"
                style={{ accentColor: 'var(--stash-accent)' }}
              />
              {s}
            </label>
          ))}
        </div>
      </div>

      <div>
        <label
          className="block text-sm mb-2"
          style={{ color: 'var(--stash-text-primary)' }}
        >
          Expires in (days){' '}
          <span style={{ color: 'var(--stash-text-secondary)' }}>
            — blank for no expiry
          </span>
        </label>
        <ThemedInput
          type="number"
          min={1}
          max={3650}
          value={expiresInDays}
          onChange={(e) =>
            setExpiresInDays(
              e.target.value === ''
                ? ''
                : Math.min(3650, Math.max(1, Number(e.target.value)))
            )
          }
          className="w-32"
        />
      </div>

      <div className="flex gap-2 pt-1">
        <ThemedPrimaryButton
          type="submit"
          disabled={submitting || !name.trim()}
        >
          {submitting ? 'Creating…' : 'Create'}
        </ThemedPrimaryButton>
        <ThemedSecondaryButton type="button" onClick={onCancel}>
          Cancel
        </ThemedSecondaryButton>
      </div>
    </form>
  );
}

const ThemedInput = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(function ThemedInput({ className = '', style, ...rest }, ref) {
  return (
    <input
      ref={ref}
      className={`px-3 py-2 rounded-md text-sm outline-none transition-all duration-150 ${
        className.includes('w-') ? className : `w-full ${className}`
      }`}
      style={{
        backgroundColor: 'var(--stash-bg-surface)',
        color: 'var(--stash-text-primary)',
        border: '1px solid var(--stash-border)',
        ...style,
      }}
      onFocus={(e) => {
        e.currentTarget.style.borderColor = 'var(--stash-accent)';
        e.currentTarget.style.boxShadow =
          '0 0 0 2px rgba(148, 226, 213, 0.15)';
      }}
      onBlur={(e) => {
        e.currentTarget.style.borderColor = 'var(--stash-border)';
        e.currentTarget.style.boxShadow = 'none';
      }}
      {...rest}
    />
  );
});

function ThemedPrimaryButton(
  props: React.ButtonHTMLAttributes<HTMLButtonElement>
) {
  const { className = '', style, ...rest } = props;
  return (
    <button
      className={`px-3 py-2 rounded-md text-sm transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
      style={{
        backgroundColor: 'var(--stash-accent)',
        color: 'var(--stash-bg-base)',
        ...style,
      }}
      onMouseEnter={(e) => {
        if (!e.currentTarget.disabled) e.currentTarget.style.opacity = '0.9';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.opacity = '1';
      }}
      {...rest}
    />
  );
}

function ThemedSecondaryButton(
  props: React.ButtonHTMLAttributes<HTMLButtonElement>
) {
  const { className = '', style, ...rest } = props;
  return (
    <button
      className={`px-3 py-2 rounded-md text-sm transition-all duration-150 ${className}`}
      style={{
        backgroundColor: 'transparent',
        color: 'var(--stash-text-primary)',
        border: '1px solid var(--stash-border)',
        ...style,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = 'transparent';
      }}
      {...rest}
    />
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
        onClick={async () => {
          // `writeText` rejects on insecure origins, denied permissions,
          // or browsers without the async Clipboard API. The token is
          // also visible in the select-all <pre> above, so on failure we
          // just nudge the user to copy it manually instead of falling
          // back to a hidden textarea hack.
          if (!navigator.clipboard?.writeText) {
            toast.error('Clipboard unavailable — copy the token manually');
            return;
          }
          try {
            await navigator.clipboard.writeText(issued.token);
            toast.success('Token copied');
          } catch (err) {
            console.error(err);
            toast.error('Failed to copy — copy the token manually');
          }
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
