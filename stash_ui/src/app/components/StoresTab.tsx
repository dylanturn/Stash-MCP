// "Stores" tab in the Organization Settings modal.
//
// Lists the content stores in the active tenant. Tenant admins can
// provision new stores via POST /tenants/{tenant_id}/stores; members
// see the list read-only.

import React, { useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { StoreSummary } from "../../api/auth";
import { useStore } from "../StoreContext";
import { CreateStoreModal } from "./CreateStoreModal";

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
              toast.error(
                "Store created, but the list failed to refresh. Reload the page to see it.",
              );
            }
          }}
        />
      )}
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
