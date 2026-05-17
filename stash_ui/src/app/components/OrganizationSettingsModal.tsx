import React, { useState } from "react";
import { X, Building2, Database, Shield } from "lucide-react";
import { useStore } from "../StoreContext";
import { StoreSummary } from "../../api/auth";

interface OrganizationSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type SettingsTab = "general" | "stores";

export function OrganizationSettingsModal({
  isOpen,
  onClose,
}: OrganizationSettingsModalProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const { current, stores } = useStore();

  if (!isOpen) return null;

  // Show only stores in the currently-selected tenant. If there's no
  // active store the modal can't infer which org you mean, so render an
  // empty-state instead of leaking other tenants' data.
  const tenantStores = current
    ? stores.filter((s) => s.tenant_slug === current.tenant_slug)
    : [];

  const tabs = [
    {
      id: "general" as SettingsTab,
      label: "General",
      icon: Building2,
    },
    {
      id: "stores" as SettingsTab,
      label: "Stores",
      icon: Database,
    },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.6)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-4xl h-[80vh] flex flex-col rounded-lg shadow-2xl overflow-hidden"
        style={{
          backgroundColor: "var(--stash-bg-surface)",
          border: "1px solid var(--stash-border)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-6 py-4 border-b"
          style={{ borderColor: "var(--stash-border)" }}
        >
          <h2
            className="text-lg font-semibold"
            style={{ color: "var(--stash-text-bright)" }}
          >
            Organization Settings
          </h2>
          <button
            onClick={onClose}
            className="p-2 rounded transition-all duration-150"
            style={{ color: "var(--stash-text-secondary)" }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = "var(--stash-bg-hover)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = "transparent";
            }}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex flex-1 overflow-hidden">
          <div
            className="w-56 border-r overflow-y-auto"
            style={{
              backgroundColor: "var(--stash-bg-base)",
              borderColor: "var(--stash-border)",
            }}
          >
            <nav className="p-2">
              {tabs.map((tab) => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md text-sm transition-all duration-150 mb-1"
                    style={{
                      backgroundColor: isActive
                        ? "var(--stash-bg-surface)"
                        : "transparent",
                      color: isActive
                        ? "var(--stash-accent)"
                        : "var(--stash-text-primary)",
                    }}
                    onMouseEnter={(e) => {
                      if (!isActive) {
                        e.currentTarget.style.backgroundColor =
                          "var(--stash-bg-hover)";
                      }
                    }}
                    onMouseLeave={(e) => {
                      if (!isActive) {
                        e.currentTarget.style.backgroundColor = "transparent";
                      }
                    }}
                  >
                    <Icon className="w-4 h-4" />
                    <span>{tab.label}</span>
                  </button>
                );
              })}
            </nav>
          </div>

          <div className="flex-1 overflow-y-auto p-6">
            {activeTab === "general" && (
              <GeneralSettings current={current} storeCount={tenantStores.length} />
            )}
            {activeTab === "stores" && (
              <StoresList current={current} stores={tenantStores} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function GeneralSettings({
  current,
  storeCount,
}: {
  current: StoreSummary | null;
  storeCount: number;
}) {
  if (!current) {
    return (
      <EmptyOrgState message="Select a store to view its organization." />
    );
  }
  return (
    <div>
      <h3
        className="text-base font-semibold mb-1"
        style={{ color: "var(--stash-text-bright)" }}
      >
        General
      </h3>
      <p
        className="text-sm mb-6"
        style={{ color: "var(--stash-text-secondary)" }}
      >
        Tenant metadata is managed by global admins via the{" "}
        <code>/admin/tenants</code> API. The fields below are read-only here.
      </p>
      <div className="space-y-4">
        <ReadOnlyField label="Display name" value={current.tenant_display_name} />
        <ReadOnlyField label="Slug" value={current.tenant_slug} mono />
        <ReadOnlyField
          label="Stores in this organization"
          value={String(storeCount)}
        />
        <div>
          <label
            className="block text-sm mb-2 flex items-center gap-2"
            style={{ color: "var(--stash-text-primary)" }}
          >
            <Shield className="w-4 h-4" />
            Your role
          </label>
          <span
            className="inline-block text-xs px-2 py-1 rounded uppercase tracking-wide"
            style={{
              backgroundColor: "var(--stash-bg-base)",
              color:
                current.role === "admin"
                  ? "var(--stash-accent)"
                  : "var(--stash-text-secondary)",
              border: `1px solid ${
                current.role === "admin"
                  ? "var(--stash-accent)"
                  : "var(--stash-border)"
              }`,
            }}
          >
            {current.role}
          </span>
        </div>
      </div>
    </div>
  );
}

function StoresList({
  current,
  stores,
}: {
  current: StoreSummary | null;
  stores: StoreSummary[];
}) {
  if (!current) {
    return (
      <EmptyOrgState message="Select a store to view its organization." />
    );
  }
  return (
    <div>
      <h3
        className="text-base font-semibold mb-1"
        style={{ color: "var(--stash-text-bright)" }}
      >
        Stores
      </h3>
      <p
        className="text-sm mb-4"
        style={{ color: "var(--stash-text-secondary)" }}
      >
        Content stores in <strong>{current.tenant_display_name}</strong>.
        Provisioning new stores is handled by global admins via the{" "}
        <code>/admin/tenants/{"{id}"}/stores</code> API.
      </p>
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
              <span
                className="text-xs px-2 py-0.5 rounded uppercase tracking-wide"
                style={{
                  backgroundColor: "var(--stash-bg-surface)",
                  color:
                    s.role === "admin"
                      ? "var(--stash-accent)"
                      : "var(--stash-text-secondary)",
                  border: `1px solid ${
                    s.role === "admin"
                      ? "var(--stash-accent)"
                      : "var(--stash-border)"
                  }`,
                }}
              >
                {s.role}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EmptyOrgState({ message }: { message: string }) {
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

function ReadOnlyField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <label
        className="block text-sm mb-2"
        style={{ color: "var(--stash-text-primary)" }}
      >
        {label}
      </label>
      <input
        type="text"
        value={value}
        readOnly
        className={`w-full px-3 py-2 rounded-md text-sm outline-none ${
          mono ? "font-mono" : ""
        }`}
        style={{
          backgroundColor: "var(--stash-bg-base)",
          color: "var(--stash-text-primary)",
          border: "1px solid var(--stash-border)",
        }}
      />
    </div>
  );
}
