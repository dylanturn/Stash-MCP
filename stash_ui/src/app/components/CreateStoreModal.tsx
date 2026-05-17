// Create-store modal. Used by the Organization Settings → Stores tab and
// by NoStoresPage (so a tenant admin can provision their very first
// store before any store exists in the tenant).
//
// POSTs to ``/tenants/{tenant_id}/stores``; requires admin role on the
// target tenant.

import React, { useEffect, useId, useState } from "react";
import { toast } from "sonner";
import { ProblemError } from "../../api/fetch";
import { createStore, StoreInfo } from "../../api/stores";

export interface CreateStoreModalProps {
  tenantId: string;
  tenantDisplayName: string;
  onClose: () => void;
  onCreated: (store: StoreInfo) => void;
}

const SLUG_MAX_LENGTH = 63;
const DISPLAY_NAME_MAX_LENGTH = 255;

export function CreateStoreModal({
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

  const titleId = useId();
  const slugId = useId();
  const displayNameId = useId();
  const gitRemoteUrlId = useId();
  const gitBranchId = useId();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !submitting) {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, submitting]);

  function validate(): Record<string, string> {
    const out: Record<string, string> = {};
    const trimmedSlug = slug.trim();
    if (!trimmedSlug) {
      out.slug = "Slug is required";
    } else if (trimmedSlug.length > SLUG_MAX_LENGTH) {
      out.slug = `Slug must be at most ${SLUG_MAX_LENGTH} characters`;
    } else if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(trimmedSlug)) {
      out.slug =
        "Slug must start with a lowercase letter or digit and contain only [a-z0-9-]";
    }
    const trimmedDisplay = displayName.trim();
    if (!trimmedDisplay) {
      out.display_name = "Display name is required";
    } else if (trimmedDisplay.length > DISPLAY_NAME_MAX_LENGTH) {
      out.display_name = `Display name must be at most ${DISPLAY_NAME_MAX_LENGTH} characters`;
    }
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
      const created = await createStore(tenantId, {
        slug: slug.trim(),
        display_name: displayName.trim(),
        git_remote_url: gitRemoteUrl.trim() || null,
        git_branch: gitBranch.trim(),
      });
      toast.success(`Created store ${created.slug}`);
      onCreated(created);
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
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
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
            id={titleId}
            className="text-base font-semibold"
            style={{ color: "var(--stash-text-bright)" }}
          >
            New store in {tenantDisplayName}
          </h3>
        </div>

        <div className="px-6 py-4 space-y-4">
          <Field
            id={slugId}
            label="Slug"
            error={fieldErrors.slug}
            hint={`Lowercase letters, digits, and dashes. Up to ${SLUG_MAX_LENGTH} characters. Used in URLs.`}
          >
            <input
              id={slugId}
              type="text"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              autoFocus
              maxLength={SLUG_MAX_LENGTH}
              className="w-full px-3 py-2 rounded-md text-sm font-mono outline-none"
              style={{
                backgroundColor: "var(--stash-bg-base)",
                color: "var(--stash-text-primary)",
                border: "1px solid var(--stash-border)",
              }}
              placeholder="docs"
            />
          </Field>

          <Field
            id={displayNameId}
            label="Display name"
            error={fieldErrors.display_name}
          >
            <input
              id={displayNameId}
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={DISPLAY_NAME_MAX_LENGTH}
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
            id={gitRemoteUrlId}
            label="Git remote URL"
            hint="Optional. If set, the store is cloned from this remote."
          >
            <input
              id={gitRemoteUrlId}
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

          <Field
            id={gitBranchId}
            label="Branch"
            error={fieldErrors.git_branch}
          >
            <input
              id={gitBranchId}
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
          <button
            type="submit"
            disabled={submitting}
            className="px-3 py-2 rounded-md text-sm transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              backgroundColor: "var(--stash-accent)",
              color: "var(--stash-bg-base)",
            }}
            onMouseEnter={(e) => {
              if (!e.currentTarget.disabled)
                e.currentTarget.style.opacity = "0.9";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = "1";
            }}
          >
            {submitting ? "Creating…" : "Create store"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={id}
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
