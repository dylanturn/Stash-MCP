import React, { useState } from "react";
import {
  X,
  Server,
  Building2,
  Trash2,
  FolderTree,
  Lock,
  LockOpen,
  Edit2,
  Palette,
} from "lucide-react";
import {
  CreateServerModal,
  ServerConfig,
} from "./CreateServerModal";
import { AppearanceSettings } from "./AppearanceSettings";

interface OrganizationSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type SettingsTab = "general" | "servers" | "appearance";

export function OrganizationSettingsModal({
  isOpen,
  onClose,
}: OrganizationSettingsModalProps) {
  const [activeTab, setActiveTab] =
    useState<SettingsTab>("general");

  if (!isOpen) return null;

  const tabs = [
    {
      id: "general" as SettingsTab,
      label: "General",
      icon: Building2,
    },
    {
      id: "servers" as SettingsTab,
      label: "MCP Servers",
      icon: Server,
    },
    {
      id: "appearance" as SettingsTab,
      label: "Appearance",
      icon: Palette,
    },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: "rgba(0, 0, 0, 0.6)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-5xl h-[85vh] flex flex-col rounded-lg shadow-2xl overflow-hidden"
        style={{
          backgroundColor: "var(--stash-bg-surface)",
          border: "1px solid var(--stash-border)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
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
              e.currentTarget.style.backgroundColor =
                "var(--stash-bg-hover)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor =
                "transparent";
            }}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content with Sidebar Navigation */}
        <div className="flex flex-1 overflow-hidden">
          {/* Sidebar Navigation */}
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
                        e.currentTarget.style.backgroundColor =
                          "transparent";
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

          {/* Main Content Area */}
          <div className="flex-1 overflow-y-auto p-6">
            {activeTab === "general" && <GeneralSettings />}
            {activeTab === "servers" && <ServerSettings />}
            {activeTab === "appearance" && <AppearanceSettings />}
          </div>
        </div>
      </div>
    </div>
  );
}

function GeneralSettings() {
  return (
    <div>
      <h3
        className="text-base font-semibold mb-4"
        style={{ color: "var(--stash-text-bright)" }}
      >
        General Settings
      </h3>
      <div className="space-y-4">
        <div>
          <label
            className="block text-sm mb-2"
            style={{ color: "var(--stash-text-primary)" }}
          >
            Organization Name
          </label>
          <input
            type="text"
            defaultValue="My Organization"
            className="w-full px-3 py-2 rounded-md text-sm outline-none transition-all duration-150"
            style={{
              backgroundColor: "var(--stash-bg-base)",
              color: "var(--stash-text-primary)",
              border: "1px solid var(--stash-border)",
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor =
                "var(--stash-accent)";
              e.currentTarget.style.boxShadow =
                "0 0 0 2px rgba(148, 226, 213, 0.1)";
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor =
                "var(--stash-border)";
              e.currentTarget.style.boxShadow = "none";
            }}
          />
        </div>
        <div>
          <label
            className="block text-sm mb-2"
            style={{ color: "var(--stash-text-primary)" }}
          >
            Description
          </label>
          <textarea
            defaultValue="Manage your MCP servers and content roots"
            rows={3}
            className="w-full px-3 py-2 rounded-md text-sm outline-none transition-all duration-150 resize-none"
            style={{
              backgroundColor: "var(--stash-bg-base)",
              color: "var(--stash-text-primary)",
              border: "1px solid var(--stash-border)",
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor =
                "var(--stash-accent)";
              e.currentTarget.style.boxShadow =
                "0 0 0 2px rgba(148, 226, 213, 0.1)";
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor =
                "var(--stash-border)";
              e.currentTarget.style.boxShadow = "none";
            }}
          />
        </div>
      </div>
    </div>
  );
}

function ServerSettings() {
  const [servers, setServers] = useState<ServerConfig[]>([]);
  const [isCreateModalOpen, setIsCreateModalOpen] =
    useState(false);
  const [editingServer, setEditingServer] =
    useState<ServerConfig | null>(null);

  const handleCreateServer = (server: ServerConfig) => {
    setServers([...servers, server]);
  };

  const handleUpdateServer = (updatedServer: ServerConfig) => {
    setServers(
      servers.map((s) =>
        s.id === updatedServer.id ? updatedServer : s,
      ),
    );
    setEditingServer(null);
  };

  const handleDeleteServer = (serverId: string) => {
    setServers(servers.filter((s) => s.id !== serverId));
  };

  const handleEditServer = (server: ServerConfig) => {
    setEditingServer(server);
    setIsCreateModalOpen(true);
  };

  const handleCloseModal = () => {
    setIsCreateModalOpen(false);
    setEditingServer(null);
  };

  return (
    <>
      <div>
        <div className="flex items-center justify-between mb-4">
          <h3
            className="text-base font-semibold"
            style={{ color: "var(--stash-text-bright)" }}
          >
            MCP Servers
          </h3>
          <button
            onClick={() => setIsCreateModalOpen(true)}
            className="px-4 py-2 rounded-md text-sm transition-all duration-150"
            style={{
              backgroundColor: "var(--stash-accent)",
              color: "var(--stash-bg-base)",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.opacity = "0.9";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = "1";
            }}
          >
            + Create Server
          </button>
        </div>
        <p
          className="text-sm mb-6"
          style={{ color: "var(--stash-text-secondary)" }}
        >
          Manage MCP servers that can access your content roots
        </p>

        {servers.length === 0 ? (
          <div
            className="p-6 rounded-md text-center"
            style={{
              backgroundColor: "var(--stash-bg-base)",
              border: "1px dashed var(--stash-border)",
            }}
          >
            <Server
              className="w-12 h-12 mx-auto mb-3"
              style={{ color: "var(--stash-text-secondary)" }}
            />
            <p
              className="text-sm"
              style={{ color: "var(--stash-text-secondary)" }}
            >
              No MCP servers configured yet
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {servers.map((server) => (
              <div
                key={server.id}
                className="p-4 rounded-md border"
                style={{
                  backgroundColor: "var(--stash-bg-base)",
                  borderColor: "var(--stash-border)",
                }}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h4
                        className="font-medium"
                        style={{
                          color: "var(--stash-text-bright)",
                        }}
                      >
                        {server.name}
                      </h4>
                    </div>
                    {server.description && (
                      <p
                        className="text-sm mb-2"
                        style={{
                          color: "var(--stash-text-secondary)",
                        }}
                      >
                        {server.description}
                      </p>
                    )}
                    <div
                      className="text-xs mb-3"
                      style={{
                        color: "var(--stash-text-secondary)",
                      }}
                    >
                      Timeout: {server.timeout}s
                    </div>

                    {/* Content Roots */}
                    {server.contentRoots &&
                      server.contentRoots.length > 0 && (
                        <div className="mt-3">
                          <div className="flex items-center gap-2 mb-2">
                            <FolderTree
                              className="w-3.5 h-3.5"
                              style={{
                                color: "var(--stash-accent)",
                              }}
                            />
                            <span
                              className="text-xs font-medium"
                              style={{
                                color:
                                  "var(--stash-text-primary)",
                              }}
                            >
                              Content Root
                            </span>
                          </div>
                          <div className="space-y-2">
                            {server.contentRoots.map(
                              (contentRoot) => (
                                <div
                                  key={contentRoot.id}
                                  className="p-2 rounded-md"
                                  style={{
                                    backgroundColor:
                                      "var(--stash-bg-surface)",
                                    border:
                                      "1px solid var(--stash-border)",
                                  }}
                                >
                                  <div className="flex items-center gap-2 mb-1">
                                    <span
                                      className="text-xs font-medium"
                                      style={{
                                        color:
                                          "var(--stash-text-bright)",
                                      }}
                                    >
                                      {contentRoot.name ||
                                        "Unnamed Content Root"}
                                    </span>
                                    <span
                                      className="text-xs px-1.5 py-0.5 rounded"
                                      style={{
                                        backgroundColor:
                                          "var(--stash-bg-base)",
                                        color:
                                          "var(--stash-accent)",
                                        border:
                                          "1px solid var(--stash-accent)",
                                      }}
                                    >
                                      {contentRoot.type ===
                                      "simple"
                                        ? "Simple"
                                        : "Virtual"}
                                    </span>
                                  </div>
                                  {contentRoot.description && (
                                    <p
                                      className="text-xs mb-1"
                                      style={{
                                        color:
                                          "var(--stash-text-secondary)",
                                      }}
                                    >
                                      {contentRoot.description}
                                    </p>
                                  )}

                                  {/* Simple Directory */}
                                  {contentRoot.type ===
                                    "simple" &&
                                    contentRoot.path && (
                                      <code
                                        className="text-xs px-1 py-0.5 rounded"
                                        style={{
                                          backgroundColor:
                                            "var(--stash-bg-base)",
                                          color:
                                            "var(--stash-text-primary)",
                                        }}
                                      >
                                        {contentRoot.path}
                                      </code>
                                    )}

                                  {/* Virtual Content Root */}
                                  {contentRoot.type ===
                                    "virtual" &&
                                    contentRoot.mountedDirectories &&
                                    contentRoot
                                      .mountedDirectories
                                      .length > 0 && (
                                      <div className="mt-1 space-y-1">
                                        {contentRoot.mountedDirectories.map(
                                          (mount) => (
                                            <div
                                              key={mount.id}
                                              className="flex items-center justify-between text-xs p-1.5 rounded"
                                              style={{
                                                backgroundColor:
                                                  "var(--stash-bg-base)",
                                              }}
                                            >
                                              <code
                                                style={{
                                                  color:
                                                    "var(--stash-text-primary)",
                                                }}
                                              >
                                                {mount.path}
                                              </code>
                                              <div className="flex items-center gap-1">
                                                {mount.permission ===
                                                "read" ? (
                                                  <Lock
                                                    className="w-3 h-3"
                                                    style={{
                                                      color:
                                                        "var(--stash-text-secondary)",
                                                    }}
                                                  />
                                                ) : (
                                                  <LockOpen
                                                    className="w-3 h-3"
                                                    style={{
                                                      color:
                                                        "var(--stash-accent)",
                                                    }}
                                                  />
                                                )}
                                                <span
                                                  style={{
                                                    color:
                                                      "var(--stash-text-secondary)",
                                                  }}
                                                >
                                                  {mount.permission ===
                                                  "read"
                                                    ? "Read"
                                                    : "Read-Write"}
                                                </span>
                                              </div>
                                            </div>
                                          ),
                                        )}
                                      </div>
                                    )}
                                </div>
                              ),
                            )}
                          </div>
                        </div>
                      )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      className="p-2 rounded transition-all duration-150"
                      style={{
                        color: "var(--stash-text-secondary)",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor =
                          "var(--stash-bg-hover)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor =
                          "transparent";
                      }}
                      title="Edit server"
                      onClick={() => handleEditServer(server)}
                    >
                      <Edit2
                        className="w-4 h-4"
                        style={{ color: "var(--stash-accent)" }}
                      />
                    </button>
                    <button
                      className="p-2 rounded transition-all duration-150"
                      style={{
                        color: "var(--stash-text-secondary)",
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor =
                          "var(--stash-bg-hover)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor =
                          "transparent";
                      }}
                      title="Delete server"
                      onClick={() =>
                        handleDeleteServer(server.id)
                      }
                    >
                      <Trash2
                        className="w-4 h-4"
                        style={{ color: "var(--stash-error)" }}
                      />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <CreateServerModal
        isOpen={isCreateModalOpen}
        onClose={handleCloseModal}
        onCreate={handleCreateServer}
        onUpdate={handleUpdateServer}
        editingServer={editingServer}
      />
    </>
  );
}