import React, { useState } from "react";
import { X, Building2, Database, Server } from "lucide-react";
import { useStore } from "../StoreContext";
import { StoreSummary } from "../../api/auth";
import { McpServersTab } from "./McpServersTab";
import { StoresTab } from "./StoresTab";

interface OrganizationSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type SettingsTab = "general" | "mcp-servers" | "stores";

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
      id: "mcp-servers" as SettingsTab,
      label: "MCP Servers",
      icon: Server,
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
              <GeneralSettings current={current} />
            )}
            {activeTab === "mcp-servers" && (
              <McpServersTab current={current} tenantStores={tenantStores} />
            )}
            {activeTab === "stores" && (
              <StoresTab current={current} stores={tenantStores} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function GeneralSettings({
  current,
}: {
  current: StoreSummary | null;
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
      </div>
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
