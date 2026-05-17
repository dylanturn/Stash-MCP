import React, { useState } from "react";
import { X, User, Palette, KeyRound, Shield } from "lucide-react";
import { Me, StoreSummary } from "../../api/auth";
import { AppearanceSettings } from "./AppearanceSettings";
import { TokensManager } from "./TokensManager";

interface UserSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  me: Me;
  stores: StoreSummary[];
}

type SettingsTab = "profile" | "appearance" | "tokens";

export function UserSettingsModal({
  isOpen,
  onClose,
  me,
  stores,
}: UserSettingsModalProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("profile");

  if (!isOpen) return null;

  const tabs = [
    { id: "profile" as SettingsTab, label: "Profile", icon: User },
    { id: "appearance" as SettingsTab, label: "Appearance", icon: Palette },
    { id: "tokens" as SettingsTab, label: "API Tokens", icon: KeyRound },
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
            Account Settings
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
            {activeTab === "profile" && (
              <ProfileSettings me={me} stores={stores} />
            )}
            {activeTab === "appearance" && <AppearanceSettings />}
            {activeTab === "tokens" && <TokensManager />}
          </div>
        </div>
      </div>
    </div>
  );
}

function ProfileSettings({ me, stores }: { me: Me; stores: StoreSummary[] }) {
  // Group memberships by tenant so the user can see their role per tenant
  // in one place. The role on each `StoreSummary` row matches the
  // tenant-level role in `me.tenant_roles`, so dedupe on tenant slug.
  const tenantRows = Array.from(
    new Map(
      stores.map((s) => [
        s.tenant_slug,
        {
          tenant_slug: s.tenant_slug,
          tenant_display_name: s.tenant_display_name,
          role: s.role,
        },
      ]),
    ).values(),
  );

  return (
    <div>
      <h3
        className="text-base font-semibold mb-4"
        style={{ color: "var(--stash-text-bright)" }}
      >
        Profile
      </h3>
      <p
        className="text-sm mb-6"
        style={{ color: "var(--stash-text-secondary)" }}
      >
        Your account details, as provided by your identity provider.
      </p>

      <div className="space-y-4">
        <ReadOnlyField label="Display name" value={me.display_name} />
        <ReadOnlyField label="Email" value={me.email} />
      </div>

      <div className="mt-8">
        <h4
          className="text-sm font-semibold mb-2 flex items-center gap-2"
          style={{ color: "var(--stash-text-bright)" }}
        >
          <Shield className="w-4 h-4" />
          Organization memberships
        </h4>
        <p
          className="text-xs mb-3"
          style={{ color: "var(--stash-text-secondary)" }}
        >
          Roles are managed by tenant admins. Contact an admin to request a
          change.
        </p>
        {tenantRows.length === 0 ? (
          <div
            className="p-4 rounded-md text-sm"
            style={{
              backgroundColor: "var(--stash-bg-base)",
              border: "1px dashed var(--stash-border)",
              color: "var(--stash-text-secondary)",
            }}
          >
            You aren't a member of any organizations yet.
          </div>
        ) : (
          <div
            className="rounded-md overflow-hidden"
            style={{ border: "1px solid var(--stash-border)" }}
          >
            {tenantRows.map((row, idx) => (
              <div
                key={row.tenant_slug}
                className="flex items-center justify-between px-4 py-2.5 text-sm"
                style={{
                  backgroundColor: "var(--stash-bg-base)",
                  borderTop:
                    idx === 0 ? "none" : "1px solid var(--stash-border)",
                }}
              >
                <div>
                  <div style={{ color: "var(--stash-text-bright)" }}>
                    {row.tenant_display_name}
                  </div>
                  <div
                    className="text-xs"
                    style={{ color: "var(--stash-text-secondary)" }}
                  >
                    {row.tenant_slug}
                  </div>
                </div>
                <span
                  className="text-xs px-2 py-0.5 rounded uppercase tracking-wide"
                  style={{
                    backgroundColor: "var(--stash-bg-surface)",
                    color:
                      row.role === "admin"
                        ? "var(--stash-accent)"
                        : "var(--stash-text-secondary)",
                    border: `1px solid ${
                      row.role === "admin"
                        ? "var(--stash-accent)"
                        : "var(--stash-border)"
                    }`,
                  }}
                >
                  {row.role}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
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
        className="w-full px-3 py-2 rounded-md text-sm outline-none"
        style={{
          backgroundColor: "var(--stash-bg-base)",
          color: "var(--stash-text-primary)",
          border: "1px solid var(--stash-border)",
        }}
      />
    </div>
  );
}

