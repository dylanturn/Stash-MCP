// Create / edit modal for an MCP-server config (spec 02).
//
// Replaces the legacy mock at ``CreateServerModal.tsx`` with three
// concrete differences: no per-mount read/write toggle (write
// capability is now a function of the tool allowlist), store-picker +
// subpath instead of free-form path strings, and a grouped tool
// catalog.

import React, { useEffect, useMemo, useState } from 'react';
import { Plus, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';
import {
  McpServer,
  MULTI_STORE_DISALLOWED_TOOLS,
  MountInput,
  TOOL_CATALOG,
  ToolGroup,
  createMcpServer,
  updateMcpServer,
} from '../../api/mcpServers';
import { StoreSummary } from '../../api/auth';
import { ProblemError } from '../../api/fetch';

interface Props {
  tenantId: string;
  tenantSlug: string;
  tenantStores: StoreSummary[];
  editing: McpServer | null;
  onClose: () => void;
  onSaved: () => void;
}

interface EditableMount {
  // Local UI ID so React keys stay stable across edits — the server's
  // ID may or may not exist yet, and on PATCH we whole-list-replace
  // anyway, so server IDs are irrelevant to the modal's state.
  uiId: string;
  store_slug: string;
  subpath: string;
  virtual_prefix: string;
}

let _uid = 0;
function genId(): string {
  _uid += 1;
  return `ui-${_uid}-${Date.now()}`;
}

function makeDefaultMount(stores: StoreSummary[]): EditableMount {
  return {
    uiId: genId(),
    store_slug: stores[0]?.slug ?? '',
    subpath: '',
    virtual_prefix: '',
  };
}

export function CreateMcpServerModal({
  tenantId,
  tenantSlug: _tenantSlug,
  tenantStores,
  editing,
  onClose,
  onSaved,
}: Props) {
  const [slug, setSlug] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [timeoutSeconds, setTimeoutSeconds] = useState(60);
  const [enabled, setEnabled] = useState(true);
  const [tools, setTools] = useState<Set<string>>(new Set());
  const [kind, setKind] = useState<'simple' | 'virtual'>('simple');
  const [mounts, setMounts] = useState<EditableMount[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (editing) {
      setSlug(editing.slug);
      setName(editing.name);
      setDescription(editing.description ?? '');
      setTimeoutSeconds(editing.timeout_seconds);
      setEnabled(editing.enabled);
      setTools(new Set(editing.tools));
      setKind(editing.kind);
      setMounts(
        editing.mounts.map((m) => ({
          uiId: genId(),
          store_slug: m.store_slug,
          subpath: m.subpath,
          virtual_prefix: m.virtual_prefix,
        })),
      );
    } else {
      setSlug('');
      setName('');
      setDescription('');
      setTimeoutSeconds(60);
      setEnabled(true);
      setTools(new Set());
      setKind('simple');
      setMounts([]);
    }
    setFieldErrors({});
  }, [editing]);

  // Number of distinct underlying stores in the current draft. If > 1
  // we disable the git/transaction tools — server-side validation will
  // also refuse them, but the UI affordance avoids the round-trip.
  const distinctStoreCount = useMemo(() => {
    const ids = new Set<string>();
    for (const m of mounts) {
      if (m.store_slug) ids.add(m.store_slug);
    }
    return ids.size;
  }, [mounts]);

  const isMultiStore = distinctStoreCount > 1;

  // If the draft becomes multi-store, drop any selected git/tx tools
  // so submit doesn't fail server-side validation. We only do this on
  // the *first* render that crosses the boundary so the user's
  // existing checkbox state stays put while they're editing.
  useEffect(() => {
    if (!isMultiStore) return;
    setTools((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const t of MULTI_STORE_DISALLOWED_TOOLS) {
        if (next.has(t)) {
          next.delete(t);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [isMultiStore]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const errors = validate();
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setFieldErrors({});
    setSubmitting(true);

    const payloadMounts: MountInput[] = mounts.map((m) => ({
      store_slug: m.store_slug,
      subpath: m.subpath.trim(),
      virtual_prefix: kind === 'simple' ? '' : m.virtual_prefix.trim(),
    }));

    try {
      if (editing) {
        await updateMcpServer(tenantId, editing.slug, {
          name: name.trim(),
          description: description.trim() || null,
          timeout_seconds: timeoutSeconds,
          enabled,
          tools: Array.from(tools).sort(),
          kind,
          mounts: payloadMounts,
        });
        toast.success(`Updated ${editing.slug}`);
      } else {
        await createMcpServer(tenantId, {
          slug: slug.trim(),
          name: name.trim(),
          description: description.trim() || null,
          timeout_seconds: timeoutSeconds,
          enabled,
          tools: Array.from(tools).sort(),
          kind,
          mounts: payloadMounts,
        });
        toast.success(`Created ${slug.trim()}`);
      }
      onSaved();
    } catch (err) {
      console.error(err);
      if (err instanceof ProblemError) {
        // Map a few known Problem types onto inline field errors;
        // everything else goes to a toast.
        const t = err.problem.type;
        if (t === '/problems/mcp-server/already-exists') {
          setFieldErrors({ slug: err.message });
        } else if (
          t === '/problems/mount/conflict' ||
          t === '/problems/mount/cross-tenant' ||
          t === '/problems/mount/invalid'
        ) {
          setFieldErrors({ _mounts: err.message });
        } else if (t === '/problems/tool-name/invalid') {
          setFieldErrors({ _tools: err.message });
        } else if (t === '/problems/mcp-server/multi-store-git-forbidden') {
          setFieldErrors({ _tools: err.message });
        } else {
          toast.error(err.message);
        }
      } else {
        toast.error(
          err instanceof Error
            ? err.message
            : 'Failed to save MCP server config',
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  function validate(): Record<string, string> {
    const out: Record<string, string> = {};
    if (!editing) {
      if (!slug.trim()) out.slug = 'Slug is required';
      else if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(slug.trim()))
        out.slug =
          'Slug must start with a lowercase letter or digit and contain only [a-z0-9-]';
    }
    if (!name.trim()) out.name = 'Display name is required';
    if (timeoutSeconds < 1 || timeoutSeconds > 600)
      out.timeout = 'Timeout must be between 1 and 600 seconds';
    if (kind === 'simple' && mounts.length > 1) {
      out._mounts =
        'Simple servers must have exactly one mount — switch to advanced or remove the extras';
    }
    for (const m of mounts) {
      if (!m.store_slug) {
        out._mounts = 'Each mount needs a store';
        break;
      }
      if (kind === 'virtual' && !m.virtual_prefix.trim()) {
        out._mounts =
          'Each mount in an advanced server needs a virtual prefix';
        break;
      }
    }
    return out;
  }

  function changeKind(next: 'simple' | 'virtual') {
    setKind(next);
    // Switching to simple collapses to a single mount (drops the
    // virtual_prefix that's no longer meaningful).
    if (next === 'simple') {
      setMounts((prev) => {
        if (prev.length === 0) return [makeDefaultMount(tenantStores)];
        return [{ ...prev[0], virtual_prefix: '' }];
      });
    } else if (mounts.length === 0) {
      setMounts([makeDefaultMount(tenantStores)]);
    }
  }

  function addMount() {
    setMounts((prev) => [
      ...prev,
      {
        ...makeDefaultMount(tenantStores),
        virtual_prefix: kind === 'virtual' ? `mount-${prev.length + 1}` : '',
      },
    ]);
  }

  function updateMount(mountUiId: string, patch: Partial<EditableMount>) {
    setMounts((prev) =>
      prev.map((m) => (m.uiId === mountUiId ? { ...m, ...patch } : m)),
    );
  }

  function removeMount(mountUiId: string) {
    setMounts((prev) => prev.filter((m) => m.uiId !== mountUiId));
  }

  function toggleTool(name: string) {
    setTools((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-3xl max-h-[90vh] flex flex-col rounded-lg shadow-2xl overflow-hidden"
        style={{
          backgroundColor: 'var(--stash-bg-surface)',
          border: '1px solid var(--stash-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-6 py-4 border-b"
          style={{ borderColor: 'var(--stash-border)' }}
        >
          <h2
            className="text-lg font-semibold"
            style={{ color: 'var(--stash-text-bright)' }}
          >
            {editing ? `Edit ${editing.slug}` : 'New MCP server'}
          </h2>
          <button
            onClick={onClose}
            className="p-2 rounded transition-all duration-150"
            style={{ color: 'var(--stash-text-secondary)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form
          onSubmit={handleSubmit}
          className="flex-1 overflow-y-auto p-6 space-y-6"
        >
          {/* Identity */}
          <section className="space-y-4">
            <FieldRow
              label="Slug"
              error={fieldErrors.slug}
              hint={
                editing
                  ? 'Slug is immutable. Delete and recreate to change it.'
                  : 'Used in API paths; lowercase letters, digits, hyphens.'
              }
            >
              <ThemedInput
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="engineering-docs"
                disabled={!!editing}
                className="font-mono"
              />
            </FieldRow>

            <FieldRow label="Display name" error={fieldErrors.name}>
              <ThemedInput
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Engineering docs"
              />
            </FieldRow>

            <FieldRow label="Description (optional)">
              <ThemedTextarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
              />
            </FieldRow>

            <div className="flex items-center gap-6">
              <FieldRow label="Timeout (seconds)" error={fieldErrors.timeout}>
                <ThemedInput
                  type="number"
                  min={1}
                  max={600}
                  value={timeoutSeconds}
                  onChange={(e) =>
                    setTimeoutSeconds(
                      Math.min(600, Math.max(1, Number(e.target.value))),
                    )
                  }
                  className="w-32"
                />
              </FieldRow>
              <label
                className="flex items-center gap-2 text-sm cursor-pointer mt-7"
                style={{ color: 'var(--stash-text-primary)' }}
              >
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  className="w-4 h-4 cursor-pointer"
                  style={{ accentColor: 'var(--stash-accent)' }}
                />
                Enabled
              </label>
            </div>
          </section>

          {/* Tools */}
          <section>
            <SectionHeading title="Tools" />
            <p
              className="text-sm mb-3"
              style={{ color: 'var(--stash-text-secondary)' }}
            >
              Tool names exposed on this server. Write capability comes
              from enabling write tools — there's no separate flag.
              {isMultiStore && (
                <>
                  {' '}
                  <span style={{ color: '#f59e0b' }}>
                    Git and transaction tools are disabled because this
                    config spans more than one store.
                  </span>
                </>
              )}
            </p>
            {fieldErrors._tools && (
              <ErrorLine message={fieldErrors._tools} />
            )}
            <div className="space-y-3">
              {(Object.keys(TOOL_CATALOG) as ToolGroup[]).map((group) => (
                <div key={group}>
                  <div
                    className="text-xs uppercase tracking-wide mb-1"
                    style={{ color: 'var(--stash-text-secondary)' }}
                  >
                    {group}
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {TOOL_CATALOG[group].map((t) => {
                      const disabled =
                        isMultiStore && MULTI_STORE_DISALLOWED_TOOLS.has(t);
                      return (
                        <label
                          key={t}
                          className="flex items-center gap-2 text-sm"
                          style={{
                            color: disabled
                              ? 'var(--stash-text-secondary)'
                              : 'var(--stash-text-primary)',
                            cursor: disabled ? 'not-allowed' : 'pointer',
                            opacity: disabled ? 0.5 : 1,
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={tools.has(t)}
                            disabled={disabled}
                            onChange={() => toggleTool(t)}
                            className="w-4 h-4"
                            style={{ accentColor: 'var(--stash-accent)' }}
                          />
                          <code className="text-xs">{t}</code>
                        </label>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Content */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <SectionHeading title="Content" />
              <div className="flex gap-2">
                <KindToggle
                  label="simple"
                  active={kind === 'simple'}
                  onClick={() => changeKind('simple')}
                />
                <KindToggle
                  label="advanced"
                  active={kind === 'virtual'}
                  onClick={() => changeKind('virtual')}
                />
              </div>
            </div>
            <p
              className="text-sm mb-3"
              style={{ color: 'var(--stash-text-secondary)' }}
            >
              {kind === 'simple' ? (
                <>
                  <em>Simple</em> servers expose one store (optionally a
                  subpath) at the agent's filesystem root.
                </>
              ) : (
                <>
                  <em>Advanced</em> servers mix one or more stores under
                  distinct virtual prefixes — useful for stitching docs
                  from multiple stores into a single view.
                </>
              )}
            </p>
            {fieldErrors._mounts && <ErrorLine message={fieldErrors._mounts} />}
            {mounts.length === 0 ? (
              <div
                className="p-4 rounded-md text-sm text-center mb-2"
                style={{
                  backgroundColor: 'var(--stash-bg-base)',
                  border: '1px dashed var(--stash-border)',
                  color: 'var(--stash-text-secondary)',
                }}
              >
                No mounts yet — this server exposes no files. Click{' '}
                <em>Add mount</em> below to mount a store.
              </div>
            ) : (
              <div
                className="p-3 rounded-md space-y-2"
                style={{
                  backgroundColor: 'var(--stash-bg-base)',
                  border: '1px solid var(--stash-border)',
                }}
              >
                {mounts.map((m) => (
                  <MountEditor
                    key={m.uiId}
                    mount={m}
                    tenantStores={tenantStores}
                    isVirtual={kind === 'virtual'}
                    canRemove={kind === 'virtual' && mounts.length > 1}
                    onChange={(patch) => updateMount(m.uiId, patch)}
                    onRemove={() => removeMount(m.uiId)}
                  />
                ))}
              </div>
            )}
            {(kind === 'virtual' || mounts.length === 0) && (
              <div className="mt-2">
                <ThemedSecondaryButton
                  type="button"
                  onClick={addMount}
                  className="inline-flex items-center gap-1 !py-1 !px-2 !text-xs"
                  disabled={kind === 'simple' && mounts.length >= 1}
                >
                  <Plus className="w-3.5 h-3.5" /> Add mount
                </ThemedSecondaryButton>
              </div>
            )}
          </section>
        </form>

        <div
          className="flex items-center justify-end gap-2 px-6 py-4 border-t"
          style={{ borderColor: 'var(--stash-border)' }}
        >
          <ThemedSecondaryButton type="button" onClick={onClose}>
            Cancel
          </ThemedSecondaryButton>
          <ThemedPrimaryButton
            type="button"
            onClick={(e) =>
              handleSubmit(e as unknown as React.FormEvent<HTMLFormElement>)
            }
            disabled={submitting}
          >
            {submitting
              ? 'Saving…'
              : editing
                ? 'Save changes'
                : 'Create server'}
          </ThemedPrimaryButton>
        </div>
      </div>
    </div>
  );
}

function MountEditor({
  mount,
  tenantStores,
  isVirtual,
  canRemove,
  onChange,
  onRemove,
}: {
  mount: EditableMount;
  tenantStores: StoreSummary[];
  isVirtual: boolean;
  canRemove: boolean;
  onChange: (patch: Partial<EditableMount>) => void;
  onRemove: () => void;
}) {
  return (
    <div
      className="flex gap-2 items-end"
      style={{ color: 'var(--stash-text-primary)' }}
    >
      <div className="flex-1">
        <label
          className="block text-xs mb-1"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          Store
        </label>
        <select
          value={mount.store_slug}
          onChange={(e) => onChange({ store_slug: e.target.value })}
          className="w-full px-2 py-1.5 rounded text-sm"
          style={{
            backgroundColor: 'var(--stash-bg-surface)',
            color: 'var(--stash-text-primary)',
            border: '1px solid var(--stash-border)',
          }}
        >
          {tenantStores.length === 0 && <option value="">(no stores)</option>}
          {tenantStores.map((s) => (
            <option key={s.id} value={s.slug}>
              {s.slug} — {s.display_name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex-1">
        <label
          className="block text-xs mb-1"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          Subpath
        </label>
        <ThemedInput
          value={mount.subpath}
          onChange={(e) => onChange({ subpath: e.target.value })}
          placeholder="(empty = store root)"
        />
      </div>
      {isVirtual && (
        <div className="flex-1">
          <label
            className="block text-xs mb-1"
            style={{ color: 'var(--stash-text-secondary)' }}
          >
            Virtual prefix
          </label>
          <ThemedInput
            value={mount.virtual_prefix}
            onChange={(e) => onChange({ virtual_prefix: e.target.value })}
            placeholder="e.g. engineering"
          />
        </div>
      )}
      {canRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="p-2 rounded"
          style={{ color: 'var(--stash-text-secondary)' }}
          title="Remove mount"
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
            e.currentTarget.style.color = '#f87171';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent';
            e.currentTarget.style.color = 'var(--stash-text-secondary)';
          }}
        >
          <Trash2 className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}

// --- small presentation helpers --------------------------------------

function SectionHeading({ title }: { title: string }) {
  return (
    <h4
      className="text-sm font-semibold mb-1"
      style={{ color: 'var(--stash-text-bright)' }}
    >
      {title}
    </h4>
  );
}

function FieldRow({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        className="block text-sm mb-1"
        style={{ color: 'var(--stash-text-primary)' }}
      >
        {label}
      </label>
      {children}
      {hint && !error && (
        <p
          className="text-xs mt-1"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          {hint}
        </p>
      )}
      {error && (
        <p className="text-xs mt-1" style={{ color: '#f87171' }}>
          {error}
        </p>
      )}
    </div>
  );
}

function ErrorLine({ message }: { message: string }) {
  return (
    <div
      className="p-2 rounded text-sm mb-3"
      style={{
        backgroundColor: 'rgba(248, 113, 113, 0.1)',
        color: '#f87171',
        border: '1px solid rgba(248, 113, 113, 0.3)',
      }}
    >
      {message}
    </div>
  );
}

function KindToggle({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-3 py-1.5 rounded text-sm transition-all duration-150"
      style={{
        backgroundColor: active
          ? 'var(--stash-accent)'
          : 'var(--stash-bg-surface)',
        color: active ? 'var(--stash-bg-base)' : 'var(--stash-text-primary)',
        border: '1px solid var(--stash-border)',
      }}
    >
      {label}
    </button>
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
      }}
      onBlur={(e) => {
        e.currentTarget.style.borderColor = 'var(--stash-border)';
      }}
      {...rest}
    />
  );
});

function ThemedTextarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { className = '', style, ...rest } = props;
  return (
    <textarea
      className={`px-3 py-2 rounded-md text-sm outline-none w-full ${className}`}
      style={{
        backgroundColor: 'var(--stash-bg-surface)',
        color: 'var(--stash-text-primary)',
        border: '1px solid var(--stash-border)',
        ...style,
      }}
      {...rest}
    />
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
      {...rest}
    />
  );
}

function ThemedSecondaryButton(
  props: React.ButtonHTMLAttributes<HTMLButtonElement>,
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
