// "Stores" tab in the Organization Settings modal.
//
// Lists the content stores in the active tenant. Tenant admins can
// provision new stores via POST /tenants/{tenant_id}/stores; members
// see the list read-only.

import React, { useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { StoreSummary } from "../../api/auth";
import { ProblemError } from "../../api/fetch";
import { createStore } from "../../api/stores";
import { useStore } from "../StoreContext";

interface Props {
  current: StoreSummary | null;
  stores: StoreSummary[];
}

export function StoresTab({ current, stores }: Props) {
  const { refreshStores } = useStore();
  const [showModal, setShowModal] = useState(false);

  if (!current) {
    return (
      <EmptyState message="Select a store to view its organization." />
    );
  }

  const isAdmin = current.role === "admin";

  return (
    <div>
      <div className="flex items-start justify-between gap-4 mb-4">
        <div className="min-w-0">
          <h3
            className="text-base font-semibold mb-1"
            style={{ color: "var(--stash-text-bright)" }}
          >
            Stores
          </h3>
          <p
            className="text-sm"
            style={{ color: "var(--stash-text-secondary)" }}
          >
            Content stores in <strong>{current.tenant_display_name}</strong>.
          </p>
        </div>
        {isAdmin && (
          <ThemedPrimaryButton
            onClick={() => setShowModal(true)}
            className="flex-shrink-0 whitespace-nowrap inline-flex items-center gap-1"
          >
            <Plus className="w-4 h-4" /> New store
          </ThemedPrimaryButton>
        )}
      </div>

      {stores.length === 0 ? (
        <div
          className="p-6 rounded-md text-center text-sm"
          style={{
            backgroundColor: "var(--stash-bg-base)",
            border: "1px dashed var(--stash-border)",
            color: "var(--stash-text-secondary)",
          }}
        >
          No stores visible to you in this organization.
          {isAdmin && ' Click "New store" to create your first one.'}
        </div>
      ) : (
        <div
          className="rounded-md overflow-hidden"
          style={{ border: "1px solid var(--stash-border)" }}
        >
          {stores.map((s, idx) => (
            <div
              key={s.id}
              className="flex items-center justify-between px-4 py-3 text-sm"
              style={{
                backgroundColor: "var(--stash-bg-base)",
                borderTop: idx === 0 ? "none" : "1px solid var(--stash-border)",
              }}
            >
              <div className="min-w-0">
                <div
                  className="font-medium"
                  style={{ color: "var(--stash-text-bright)" }}
                >
                  {s.display_name}
                </div>
                <code
                  className="text-xs"
                  style={{ color: "var(--stash-text-secondary)" }}
                >
                  /{s.tenant_slug}/{s.slug}
                </code>
              </div>
            </div>
          ))}
        </div>
      )}

      {showModal && (
        <CreateStoreModal
          tenantId={current.tenant_id}
          tenantDisplayName={current.tenant_display_name}
          onClose={() => setShowModal(false)}
          onCreated={async () => {
            setShowModal(false);
            try {
              await refreshStores();
            } catch (err) {
              console.error(err);
            }
          }}
        />
      )}
    </div>
  );
}

interface CreateStoreModalProps {
  tenantId: string;
  tenantDisplayName: string;
  onClose: () => void;
  onCreated: () => void;
}

function CreateStoreModal({
  tenantId,
  tenantDisplayName,
  onClose,
  onCreated,
}: CreateStoreModalProps) {
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [gitRemoteUrl, setGitRemoteUrl] = useState("");
  const [gitBranch, setGitBranch] = useState("main");
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  function validate(): Record<string, string> {
    const out: Record<string, string> = {};
    if (!slug.trim()) out.slug = "Slug is required";
    else if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(slug.trim()))
      out.slug =
        "Slug must start with a lowercase letter or digit and contain only [a-z0-9-]";
    if (!displayName.trim()) out.display_name = "Display name is required";
    if (!gitBranch.trim()) out.git_branch = "Branch is required";
    return out;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const errors = validate();
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setFieldErrors({});
    setSubmitting(true);
    try {
      await createStore(tenantId, {
        slug: slug.trim(),
        display_name: displayName.trim(),
        git_remote_url: gitRemoteUrl.trim() || null,
        git_branch: gitBranch.trim(),
      });
      toast.success(`Created store ${slug.trim()}`);
      onCreated();
    } catch (err) {
      console.error(err);
      if (err instanceof ProblemError) {
        const t = err.problem.type;
        if (t === "/problems/store/already-exists") {
          setFieldErrors({ slug: err.message });
        } else {
          toast.error(err.message);
        }
      } else {
        toast.error(
          err instanceof Error ? err.message : "Failed to create store",
        );
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.6)" }}
      onClick={onClose}
    >
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-lg shadow-2xl overflow-hidden"
        style={{
          backgroundColor: "var(--stash-bg-surface)",
          border: "1px solid var(--stash-border)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="px-6 py-4 border-b"
          style={{ borderColor: "var(--stash-border)" }}
        >
          <h3
            className="text-base font-semibold"
            style={{ color: "var(--stash-text-bright)" }}
          >
            New store in {tenantDisplayName}
          </h3>
        </div>

        <div className="px-6 py-4 space-y-4">
          <Field
            label="Slug"
            error={fieldErrors.slug}
            hint="Lowercase letters, digits, and dashes. Used in URLs."
          >
            <input
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              autoFocus
              className="w-full px-3 py-2 rounded-md text-sm font-mono outline-none"
              style={{
                backgroundColor: "var(--stash-bg-base)",
                color: "var(--stash-text-primary)",
                border: "1px solid var(--stash-border)",
              }}
              placeholder="docs"
            />
          </Field>

          <Field label="Display name" error={fieldErrors.display_name}>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full px-3 py-2 rounded-md text-sm outline-none"
              style={{
                backgroundColor: "var(--stash-bg-base)",
                color: "var(--stash-text-primary)",
                border: "1px solid var(--stash-border)",
              }}
              placeholder="Docs"
            />
          </Field>

          <Field
            label="Git remote URL"
            hint="Optional. If set, the store is cloned from this remote."
          >
            <input
              type="text"
              value={gitRemoteUrl}
              onChange={(e) => setGitRemoteUrl(e.target.value)}
              className="w-full px-3 py-2 rounded-md text-sm font-mono outline-none"
              style={{
                backgroundColor: "var(--stash-bg-base)",
                color: "var(--stash-text-primary)",
                border: "1px solid var(--stash-border)",
              }}
              placeholder="git@github.com:acme/docs.git"
            />
          </Field>

          <Field label="Branch" error={fieldErrors.git_branch}>
            <input
              type="text"
              value={gitBranch}
              onChange={(e) => setGitBranch(e.target.value)}
              className="w-full px-3 py-2 rounded-md text-sm font-mono outline-none"
              style={{
                backgroundColor: "var(--stash-bg-base)",
                color: "var(--stash-text-primary)",
                border: "1px solid var(--stash-border)",
              }}
            />
          </Field>
        </div>

        <div
          className="flex items-center justify-end gap-2 px-6 py-3 border-t"
          style={{ borderColor: "var(--stash-border)" }}
        >
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-2 rounded-md text-sm transition-all duration-150 disabled:opacity-50"
            style={{
              backgroundColor: "transparent",
              color: "var(--stash-text-primary)",
              border: "1px solid var(--stash-border)",
            }}
          >
            Cancel
          </button>
          <ThemedPrimaryButton type="submit" disabled={submitting}>
            {submitting ? "Creating…" : "Create store"}
          </ThemedPrimaryButton>
        </div>
      </form>
    </div>
  );
}

function Field({
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
        className="block text-sm mb-2"
        style={{ color: "var(--stash-text-primary)" }}
      >
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-xs mt-1" style={{ color: "#f87171" }}>
          {error}
        </p>
      ) : hint ? (
        <p
          className="text-xs mt-1"
          style={{ color: "var(--stash-text-secondary)" }}
        >
          {hint}
        </p>
      ) : null}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div
      className="p-6 rounded-md text-sm"
      style={{
        backgroundColor: "var(--stash-bg-base)",
        border: "1px dashed var(--stash-border)",
        color: "var(--stash-text-secondary)",
      }}
    >
      {message}
    </div>
  );
}

function ThemedPrimaryButton(
  props: React.ButtonHTMLAttributes<HTMLButtonElement>,
) {
  const { className = "", style, ...rest } = props;
  return (
    <button
      className={`px-3 py-2 rounded-md text-sm transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed ${className}`}
      style={{
        backgroundColor: "var(--stash-accent)",
        color: "var(--stash-bg-base)",
        ...style,
      }}
      onMouseEnter={(e) => {
        if (!e.currentTarget.disabled) e.currentTarget.style.opacity = "0.9";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.opacity = "1";
      }}
      {...rest}
    />
  );
}
