// "MCP Servers" tab in the Organization Settings modal (spec 02).
//
// Renders the list of configs for the active tenant and hosts the
// create/edit modal. Gated on ``role === 'admin'`` for mutations; a
// non-admin member sees the list read-only.

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Plus, Trash2, Pencil, Power, PowerOff } from 'lucide-react';
import { toast } from 'sonner';
import {
  McpServer,
  deleteMcpServer,
  listMcpServers,
} from '../../api/mcpServers';
import { ProblemError } from '../../api/fetch';
import { StoreSummary } from '../../api/auth';
import { CreateMcpServerModal } from './CreateMcpServerModal';

interface Props {
  current: StoreSummary | null;
  tenantStores: StoreSummary[];
}

export function McpServersTab({ current, tenantStores }: Props) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<McpServer | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    if (!current) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await listMcpServers(current.tenant_id);
      if (!mountedRef.current) return;
      setServers(data);
    } catch (err) {
      if (!mountedRef.current) return;
      console.error(err);
      toast.error(
        err instanceof ProblemError
          ? err.message
          : 'Failed to load MCP server configs',
      );
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [current]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  if (!current) {
    return (
      <EmptyState message="Select a store to view its organization." />
    );
  }

  const isAdmin = current.role === 'admin';

  async function handleDelete(server: McpServer) {
    if (!current) return;
    // Typed-slug guard: the user must retype the slug to confirm. We
    // borrow the browser prompt rather than building a custom modal
    // because the destructive surface is small and the existing
    // store-delete flow uses the same primitive.
    const typed = window.prompt(
      `Type "${server.slug}" to confirm deletion. This unbinds any tokens scoped to it.`,
    );
    if (typed !== server.slug) {
      if (typed !== null) {
        toast.error('Slug did not match — config was not deleted.');
      }
      return;
    }
    try {
      await deleteMcpServer(current.tenant_id, server.slug);
      toast.success(`Deleted ${server.slug}`);
      refresh();
    } catch (err) {
      console.error(err);
      toast.error(
        err instanceof ProblemError
          ? err.message
          : 'Failed to delete MCP server config',
      );
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
            MCP Servers
          </h3>
          <p
            className="text-sm"
            style={{ color: 'var(--stash-text-secondary)' }}
          >
            Named server configs scoped to{' '}
            <strong>{current.tenant_display_name}</strong>. Each config
            picks a subset of tools to expose and one or more content
            roots composed from the stores in this organization. Tokens
            bind to a config in the API Tokens tab.
          </p>
        </div>
        {isAdmin && (
          <ThemedPrimaryButton
            onClick={() => {
              setEditing(null);
              setShowModal(true);
            }}
            className="flex-shrink-0 whitespace-nowrap inline-flex items-center gap-1"
          >
            <Plus className="w-4 h-4" /> New server
          </ThemedPrimaryButton>
        )}
      </div>

      {loading ? (
        <p style={{ color: 'var(--stash-text-secondary)' }}>Loading…</p>
      ) : servers.length === 0 ? (
        <div
          className="p-6 rounded-md text-center text-sm"
          style={{
            backgroundColor: 'var(--stash-bg-base)',
            border: '1px dashed var(--stash-border)',
            color: 'var(--stash-text-secondary)',
          }}
        >
          No MCP server configs yet.
          {isAdmin && ' Click "New server" to create your first one.'}
        </div>
      ) : (
        <div
          className="rounded-md overflow-hidden"
          style={{ border: '1px solid var(--stash-border)' }}
        >
          {servers.map((s, idx) => (
            <ServerRow
              key={s.id}
              server={s}
              isFirst={idx === 0}
              isAdmin={isAdmin}
              onEdit={() => {
                setEditing(s);
                setShowModal(true);
              }}
              onDelete={() => handleDelete(s)}
            />
          ))}
        </div>
      )}

      {showModal && current && (
        <CreateMcpServerModal
          tenantId={current.tenant_id}
          tenantSlug={current.tenant_slug}
          tenantStores={tenantStores}
          editing={editing}
          onClose={() => {
            setShowModal(false);
            setEditing(null);
          }}
          onSaved={() => {
            setShowModal(false);
            setEditing(null);
            refresh();
          }}
        />
      )}
    </div>
  );
}

function ServerRow({
  server,
  isFirst,
  isAdmin,
  onEdit,
  onDelete,
}: {
  server: McpServer;
  isFirst: boolean;
  isAdmin: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const mountCount = server.mounts.length;
  return (
    <div
      className="flex items-center justify-between px-4 py-3 text-sm gap-3"
      style={{
        backgroundColor: 'var(--stash-bg-base)',
        borderTop: isFirst ? 'none' : '1px solid var(--stash-border)',
      }}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className="font-medium truncate"
            style={{ color: 'var(--stash-text-bright)' }}
          >
            {server.name}
          </span>
          {server.enabled ? (
            <Power
              className="w-3.5 h-3.5 flex-shrink-0"
              style={{ color: 'var(--stash-accent)' }}
              aria-label="enabled"
            />
          ) : (
            <PowerOff
              className="w-3.5 h-3.5 flex-shrink-0"
              style={{ color: 'var(--stash-text-secondary)' }}
              aria-label="disabled"
            />
          )}
        </div>
        <div
          className="text-xs"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          <code>{server.slug}</code> · {server.tools.length} tool
          {server.tools.length === 1 ? '' : 's'} · {server.kind} ·{' '}
          {mountCount} mount{mountCount === 1 ? '' : 's'}
        </div>
        {server.description && (
          <div
            className="text-xs mt-1 truncate"
            style={{ color: 'var(--stash-text-secondary)' }}
          >
            {server.description}
          </div>
        )}
      </div>
      {isAdmin && (
        <div className="flex items-center gap-1 flex-shrink-0">
          <IconButton onClick={onEdit} title="Edit">
            <Pencil className="w-4 h-4" />
          </IconButton>
          <IconButton onClick={onDelete} title="Delete" destructive>
            <Trash2 className="w-4 h-4" />
          </IconButton>
        </div>
      )}
    </div>
  );
}

function IconButton({
  children,
  onClick,
  title,
  destructive = false,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
  destructive?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="p-1.5 rounded transition-all duration-150"
      style={{
        color: destructive
          ? 'var(--stash-text-secondary)'
          : 'var(--stash-text-primary)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
        if (destructive) e.currentTarget.style.color = '#f87171';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = 'transparent';
        e.currentTarget.style.color = destructive
          ? 'var(--stash-text-secondary)'
          : 'var(--stash-text-primary)';
      }}
    >
      {children}
    </button>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div
      className="p-6 rounded-md text-sm"
      style={{
        backgroundColor: 'var(--stash-bg-base)',
        border: '1px dashed var(--stash-border)',
        color: 'var(--stash-text-secondary)',
      }}
    >
      {message}
    </div>
  );
}

function ThemedPrimaryButton(
  props: React.ButtonHTMLAttributes<HTMLButtonElement>,
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
