import React, { useState, useEffect } from 'react';
import { X, Server, AlertCircle, Plus, Trash2, Lock, LockOpen, FolderTree, Key, Copy, Eye, EyeOff, RefreshCw } from 'lucide-react';

interface CreateServerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (server: ServerConfig) => void;
  onUpdate?: (server: ServerConfig) => void;
  editingServer?: ServerConfig | null;
}

export interface MountedDirectory {
  id: string;
  path: string;
  permission: 'read' | 'read-write';
}

export interface ContentRootConfig {
  id: string;
  name: string;
  description: string;
  type: 'simple' | 'virtual';
  path?: string; // For simple type
  mountedDirectories?: MountedDirectory[]; // For virtual type
}

export interface APIKey {
  id: string;
  key: string;
  name: string;
  createdAt: string;
  lastUsed?: string;
}

export interface ServerConfig {
  id: string;
  name: string;
  description: string;
  timeout?: number;
  contentRoots: ContentRootConfig[];
  oauthClientId?: string;
  oauthClientSecret?: string;
  apiKeys?: APIKey[];
}

export function CreateServerModal({ isOpen, onClose, onCreate, onUpdate, editingServer }: CreateServerModalProps) {
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    timeout: 30,
  });

  const [contentRoots, setContentRoots] = useState<ContentRootConfig[]>([]);
  const [oauthClientId, setOauthClientId] = useState('');
  const [oauthClientSecret, setOauthClientSecret] = useState('');
  const [apiKeys, setApiKeys] = useState<APIKey[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [showClientSecret, setShowClientSecret] = useState(false);
  const [copiedItem, setCopiedItem] = useState<string | null>(null);

  // Reset form when modal opens or editing server changes
  useEffect(() => {
    if (isOpen) {
      if (editingServer) {
        setFormData({
          name: editingServer.name,
          description: editingServer.description,
          timeout: editingServer.timeout || 30,
        });
        setContentRoots(editingServer.contentRoots || []);
        setOauthClientId(editingServer.oauthClientId || '');
        setOauthClientSecret(editingServer.oauthClientSecret || '');
        setApiKeys(editingServer.apiKeys || []);
      } else {
        setFormData({
          name: '',
          description: '',
          timeout: 30,
        });
        setContentRoots([]);
        setOauthClientId('');
        setOauthClientSecret('');
        setApiKeys([]);
      }
      setErrors({});
      setShowClientSecret(false);
      setCopiedItem(null);
    }
  }, [isOpen, editingServer]);

  if (!isOpen) return null;

  const validateForm = () => {
    const newErrors: Record<string, string> = {};

    if (!formData.name.trim()) {
      newErrors.name = 'Server name is required';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const generateRandomString = (length: number) => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    let result = '';
    for (let i = 0; i < length; i++) {
      result += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return result;
  };

  const generateOAuthCredentials = () => {
    setOauthClientId(`mcp_${generateRandomString(24)}`);
    setOauthClientSecret(`mcp_secret_${generateRandomString(48)}`);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!validateForm()) return;

    const server: ServerConfig = {
      id: editingServer?.id || `server-${Date.now()}`,
      name: formData.name,
      description: formData.description,
      timeout: formData.timeout,
      contentRoots,
      oauthClientId: oauthClientId || undefined,
      oauthClientSecret: oauthClientSecret || undefined,
      apiKeys,
    };

    if (editingServer) {
      onUpdate?.(server);
    } else {
      onCreate(server);
    }
    handleClose();
  };

  const handleClose = () => {
    setFormData({
      name: '',
      description: '',
      timeout: 30,
    });
    setContentRoots([]);
    setOauthClientId('');
    setOauthClientSecret('');
    setApiKeys([]);
    setErrors({});
    onClose();
  };

  const addContentRoot = () => {
    const newContentRoot: ContentRootConfig = {
      id: `content-root-${Date.now()}`,
      name: '',
      description: '',
      type: 'simple',
      path: '',
    };
    setContentRoots([...contentRoots, newContentRoot]);
  };

  const removeContentRoot = (id: string) => {
    setContentRoots(contentRoots.filter((cr) => cr.id !== id));
  };

  const updateContentRoot = (id: string, updates: Partial<ContentRootConfig>) => {
    setContentRoots(contentRoots.map((cr) => (cr.id === id ? { ...cr, ...updates } : cr)));
  };

  const addMountedDirectory = (contentRootId: string) => {
    const newMountedDirectory: MountedDirectory = {
      id: `mount-${Date.now()}`,
      path: '',
      permission: 'read',
    };
    setContentRoots(
      contentRoots.map((cr) =>
        cr.id === contentRootId
          ? {
              ...cr,
              mountedDirectories: [...(cr.mountedDirectories || []), newMountedDirectory],
            }
          : cr
      )
    );
  };

  const removeMountedDirectory = (contentRootId: string, mountId: string) => {
    setContentRoots(
      contentRoots.map((cr) =>
        cr.id === contentRootId
          ? {
              ...cr,
              mountedDirectories: cr.mountedDirectories?.filter((m) => m.id !== mountId),
            }
          : cr
      )
    );
  };

  const updateMountedDirectory = (
    contentRootId: string,
    mountId: string,
    updates: Partial<MountedDirectory>
  ) => {
    setContentRoots(
      contentRoots.map((cr) =>
        cr.id === contentRootId
          ? {
              ...cr,
              mountedDirectories: cr.mountedDirectories?.map((m) =>
                m.id === mountId ? { ...m, ...updates } : m
              ),
            }
          : cr
      )
    );
  };

  const provisionAPIKey = () => {
    const newApiKey: APIKey = {
      id: `api-key-${Date.now()}`,
      key: `stash_${generateRandomString(32)}`,
      name: `API Key ${apiKeys.length + 1}`,
      createdAt: new Date().toISOString(),
    };
    setApiKeys([...apiKeys, newApiKey]);
  };

  const revokeAPIKey = (id: string) => {
    setApiKeys(apiKeys.filter((key) => key.id !== id));
  };

  const updateAPIKeyName = (id: string, name: string) => {
    setApiKeys(apiKeys.map((key) => (key.id === id ? { ...key, name } : key)));
  };

  const copyToClipboard = (text: string, itemId: string) => {
    // Fallback method for clipboard API
    try {
      // Try modern Clipboard API first
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          setCopiedItem(itemId);
          setTimeout(() => setCopiedItem(null), 2000);
        }).catch(() => {
          // Fallback if clipboard API fails
          fallbackCopy(text, itemId);
        });
      } else {
        // Use fallback if Clipboard API not available
        fallbackCopy(text, itemId);
      }
    } catch (err) {
      fallbackCopy(text, itemId);
    }
  };

  const fallbackCopy = (text: string, itemId: string) => {
    // Create a temporary textarea
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    
    try {
      document.execCommand('copy');
      setCopiedItem(itemId);
      setTimeout(() => setCopiedItem(null), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    } finally {
      document.body.removeChild(textarea);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
      onClick={handleClose}
    >
      <div
        className="w-full max-w-3xl flex flex-col rounded-lg shadow-2xl overflow-hidden"
        style={{
          backgroundColor: 'var(--stash-bg-surface)',
          border: '1px solid var(--stash-border)',
          maxHeight: '90vh',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4 border-b"
          style={{ borderColor: 'var(--stash-border)' }}
        >
          <div className="flex items-center gap-3">
            <div
              className="p-2 rounded"
              style={{ backgroundColor: 'var(--stash-bg-base)' }}
            >
              <Server
                className="w-5 h-5"
                style={{ color: 'var(--stash-accent)' }}
              />
            </div>
            <h2
              className="text-lg font-semibold"
              style={{ color: 'var(--stash-text-bright)' }}
            >
              {editingServer ? 'Edit MCP Server' : 'Create MCP Server'}
            </h2>
          </div>
          <button
            onClick={handleClose}
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

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6">
          <div className="space-y-6">
            {/* Server Details Section */}
            <div>
              <h3
                className="text-sm font-semibold mb-3"
                style={{ color: 'var(--stash-text-bright)' }}
              >
                Server Details
              </h3>
              <div className="space-y-4">
                {/* Server Name */}
                <div>
                  <label
                    className="block text-sm font-medium mb-2"
                    style={{ color: 'var(--stash-text-primary)' }}
                  >
                    Server Name <span style={{ color: 'var(--stash-error)' }}>*</span>
                  </label>
                  <input
                    type="text"
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="e.g., Stash MCP Server"
                    className="w-full px-3 py-2 rounded-md text-sm outline-none transition-all duration-150"
                    style={{
                      backgroundColor: 'var(--stash-bg-base)',
                      color: 'var(--stash-text-primary)',
                      border: `1px solid ${errors.name ? 'var(--stash-error)' : 'var(--stash-border)'}`,
                    }}
                    onFocus={(e) => {
                      if (!errors.name) {
                        e.currentTarget.style.borderColor = 'var(--stash-accent)';
                        e.currentTarget.style.boxShadow = '0 0 0 2px rgba(148, 226, 213, 0.1)';
                      }
                    }}
                    onBlur={(e) => {
                      e.currentTarget.style.borderColor = errors.name
                        ? 'var(--stash-error)'
                        : 'var(--stash-border)';
                      e.currentTarget.style.boxShadow = 'none';
                    }}
                  />
                  {errors.name && (
                    <div className="flex items-center gap-1 mt-1">
                      <AlertCircle className="w-3 h-3" style={{ color: 'var(--stash-error)' }} />
                      <span className="text-xs" style={{ color: 'var(--stash-error)' }}>
                        {errors.name}
                      </span>
                    </div>
                  )}
                </div>

                {/* Description */}
                <div>
                  <label
                    className="block text-sm font-medium mb-2"
                    style={{ color: 'var(--stash-text-primary)' }}
                  >
                    Description
                  </label>
                  <textarea
                    value={formData.description}
                    onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                    placeholder="Brief description of what this server does"
                    rows={2}
                    className="w-full px-3 py-2 rounded-md text-sm outline-none transition-all duration-150 resize-none"
                    style={{
                      backgroundColor: 'var(--stash-bg-base)',
                      color: 'var(--stash-text-primary)',
                      border: '1px solid var(--stash-border)',
                    }}
                    onFocus={(e) => {
                      e.currentTarget.style.borderColor = 'var(--stash-accent)';
                      e.currentTarget.style.boxShadow = '0 0 0 2px rgba(148, 226, 213, 0.1)';
                    }}
                    onBlur={(e) => {
                      e.currentTarget.style.borderColor = 'var(--stash-border)';
                      e.currentTarget.style.boxShadow = 'none';
                    }}
                  />
                </div>

                {/* Timeout */}
                <div>
                  <label
                    className="block text-sm font-medium mb-2"
                    style={{ color: 'var(--stash-text-primary)' }}
                  >
                    Timeout (seconds)
                  </label>
                  <input
                    type="number"
                    value={formData.timeout}
                    onChange={(e) =>
                      setFormData({ ...formData, timeout: parseInt(e.target.value) || 30 })
                    }
                    min={1}
                    max={300}
                    className="w-full px-3 py-2 rounded-md text-sm outline-none transition-all duration-150"
                    style={{
                      backgroundColor: 'var(--stash-bg-base)',
                      color: 'var(--stash-text-primary)',
                      border: '1px solid var(--stash-border)',
                    }}
                    onFocus={(e) => {
                      e.currentTarget.style.borderColor = 'var(--stash-accent)';
                      e.currentTarget.style.boxShadow = '0 0 0 2px rgba(148, 226, 213, 0.1)';
                    }}
                    onBlur={(e) => {
                      e.currentTarget.style.borderColor = 'var(--stash-border)';
                      e.currentTarget.style.boxShadow = 'none';
                    }}
                  />
                </div>
              </div>
            </div>

            {/* Divider */}
            <div style={{ borderTop: '1px solid var(--stash-border)' }} />

            {/* OAuth Credentials Section - Only shown when editing */}
            {editingServer && (
              <>
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h3
                      className="text-sm font-semibold"
                      style={{ color: 'var(--stash-text-bright)' }}
                    >
                      OAuth Credentials
                    </h3>
                    <button
                      type="button"
                      onClick={generateOAuthCredentials}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs transition-all duration-150"
                      style={{
                        backgroundColor: 'var(--stash-bg-base)',
                        color: 'var(--stash-accent)',
                        border: '1px solid var(--stash-accent)',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--stash-bg-base)';
                      }}
                    >
                      <RefreshCw className="w-3 h-3" />
                      {oauthClientId ? 'Regenerate' : 'Generate'} Credentials
                    </button>
                  </div>
                  <p className="text-xs mb-4" style={{ color: 'var(--stash-text-secondary)' }}>
                    OAuth credentials for secure authentication
                  </p>

                  {oauthClientId ? (
                    <div className="space-y-3">
                      {/* Client ID */}
                      <div>
                        <label
                          className="block text-xs font-medium mb-2"
                          style={{ color: 'var(--stash-text-primary)' }}
                        >
                          Client ID
                        </label>
                        <div className="flex gap-2">
                          <input
                            type="text"
                            value={oauthClientId}
                            readOnly
                            className="flex-1 px-3 py-2 rounded-md text-xs outline-none"
                            style={{
                              backgroundColor: 'var(--stash-bg-base)',
                              color: 'var(--stash-text-primary)',
                              border: '1px solid var(--stash-border)',
                            }}
                          />
                          <button
                            type="button"
                            onClick={() => copyToClipboard(oauthClientId, 'client-id')}
                            className="px-3 py-2 rounded-md text-xs transition-all duration-150"
                            style={{
                              backgroundColor: 'var(--stash-bg-base)',
                              color: 'var(--stash-text-secondary)',
                              border: '1px solid var(--stash-border)',
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.backgroundColor = 'var(--stash-bg-base)';
                            }}
                          >
                            {copiedItem === 'client-id' ? (
                              <span style={{ color: 'var(--stash-accent)' }}>Copied!</span>
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                          </button>
                        </div>
                      </div>

                      {/* Client Secret */}
                      <div>
                        <label
                          className="block text-xs font-medium mb-2"
                          style={{ color: 'var(--stash-text-primary)' }}
                        >
                          Client Secret
                        </label>
                        <div className="flex gap-2">
                          <input
                            type={showClientSecret ? 'text' : 'password'}
                            value={oauthClientSecret}
                            readOnly
                            className="flex-1 px-3 py-2 rounded-md text-xs outline-none"
                            style={{
                              backgroundColor: 'var(--stash-bg-base)',
                              color: 'var(--stash-text-primary)',
                              border: '1px solid var(--stash-border)',
                            }}
                          />
                          <button
                            type="button"
                            onClick={() => setShowClientSecret(!showClientSecret)}
                            className="px-3 py-2 rounded-md text-xs transition-all duration-150"
                            style={{
                              backgroundColor: 'var(--stash-bg-base)',
                              color: 'var(--stash-text-secondary)',
                              border: '1px solid var(--stash-border)',
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.backgroundColor = 'var(--stash-bg-base)';
                            }}
                          >
                            {showClientSecret ? (
                              <EyeOff className="w-3.5 h-3.5" />
                            ) : (
                              <Eye className="w-3.5 h-3.5" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => copyToClipboard(oauthClientSecret, 'client-secret')}
                            className="px-3 py-2 rounded-md text-xs transition-all duration-150"
                            style={{
                              backgroundColor: 'var(--stash-bg-base)',
                              color: 'var(--stash-text-secondary)',
                              border: '1px solid var(--stash-border)',
                            }}
                            onMouseEnter={(e) => {
                              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                            }}
                            onMouseLeave={(e) => {
                              e.currentTarget.style.backgroundColor = 'var(--stash-bg-base)';
                            }}
                          >
                            {copiedItem === 'client-secret' ? (
                              <span style={{ color: 'var(--stash-accent)' }}>Copied!</span>
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div
                      className="p-4 rounded-md text-center text-sm"
                      style={{
                        backgroundColor: 'var(--stash-bg-base)',
                        color: 'var(--stash-text-secondary)',
                        border: '1px dashed var(--stash-border)',
                      }}
                    >
                      No OAuth credentials generated yet
                    </div>
                  )}
                </div>

                {/* Divider */}
                <div style={{ borderTop: '1px solid var(--stash-border)' }} />

                {/* API Keys Section - Only shown when editing */}
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h3
                      className="text-sm font-semibold"
                      style={{ color: 'var(--stash-text-bright)' }}
                    >
                      API Keys
                    </h3>
                    <button
                      type="button"
                      onClick={provisionAPIKey}
                      className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs transition-all duration-150"
                      style={{
                        backgroundColor: 'var(--stash-bg-base)',
                        color: 'var(--stash-accent)',
                        border: '1px solid var(--stash-accent)',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--stash-bg-base)';
                      }}
                    >
                      <Plus className="w-3 h-3" />
                      Provision API Key
                    </button>
                  </div>
                  <p className="text-xs mb-4" style={{ color: 'var(--stash-text-secondary)' }}>
                    Manage API keys for programmatic access to this server
                  </p>

                  {apiKeys.length === 0 ? (
                    <div
                      className="p-4 rounded-md text-center text-sm"
                      style={{
                        backgroundColor: 'var(--stash-bg-base)',
                        color: 'var(--stash-text-secondary)',
                        border: '1px dashed var(--stash-border)',
                      }}
                    >
                      No API keys provisioned yet
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {apiKeys.map((apiKey) => (
                        <div
                          key={apiKey.id}
                          className="p-3 rounded-md border"
                          style={{
                            backgroundColor: 'var(--stash-bg-base)',
                            borderColor: 'var(--stash-border)',
                          }}
                        >
                          <div className="flex items-start gap-3">
                            <div
                              className="p-1.5 rounded mt-0.5"
                              style={{ backgroundColor: 'var(--stash-bg-surface)' }}
                            >
                              <Key className="w-3.5 h-3.5" style={{ color: 'var(--stash-accent)' }} />
                            </div>
                            <div className="flex-1 min-w-0">
                              <input
                                type="text"
                                value={apiKey.name}
                                onChange={(e) => updateAPIKeyName(apiKey.id, e.target.value)}
                                className="w-full px-2 py-1 rounded-md text-xs font-medium outline-none mb-2 transition-all duration-150"
                                style={{
                                  backgroundColor: 'var(--stash-bg-surface)',
                                  color: 'var(--stash-text-bright)',
                                  border: '1px solid var(--stash-border)',
                                }}
                                onFocus={(e) => {
                                  e.currentTarget.style.borderColor = 'var(--stash-accent)';
                                  e.currentTarget.style.boxShadow = '0 0 0 1px rgba(148, 226, 213, 0.1)';
                                }}
                                onBlur={(e) => {
                                  e.currentTarget.style.borderColor = 'var(--stash-border)';
                                  e.currentTarget.style.boxShadow = 'none';
                                }}
                              />
                              <div className="flex gap-2 mb-2">
                                <code
                                  className="flex-1 px-2 py-1 rounded text-xs truncate"
                                  style={{
                                    backgroundColor: 'var(--stash-bg-surface)',
                                    color: 'var(--stash-text-primary)',
                                    border: '1px solid var(--stash-border)',
                                  }}
                                >
                                  {apiKey.key}
                                </code>
                                <button
                                  type="button"
                                  onClick={() => copyToClipboard(apiKey.key, apiKey.id)}
                                  className="px-2 py-1 rounded-md text-xs transition-all duration-150"
                                  style={{
                                    backgroundColor: 'var(--stash-bg-surface)',
                                    color: 'var(--stash-text-secondary)',
                                    border: '1px solid var(--stash-border)',
                                  }}
                                  onMouseEnter={(e) => {
                                    e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                                  }}
                                  onMouseLeave={(e) => {
                                    e.currentTarget.style.backgroundColor = 'var(--stash-bg-surface)';
                                  }}
                                >
                                  {copiedItem === apiKey.id ? (
                                    <span style={{ color: 'var(--stash-accent)' }}>Copied!</span>
                                  ) : (
                                    <Copy className="w-3 h-3" />
                                  )}
                                </button>
                              </div>
                              <div className="flex items-center justify-between text-xs">
                                <span style={{ color: 'var(--stash-text-secondary)' }}>
                                  Created: {new Date(apiKey.createdAt).toLocaleDateString()}
                                </span>
                                {apiKey.lastUsed && (
                                  <span style={{ color: 'var(--stash-text-secondary)' }}>
                                    Last used: {new Date(apiKey.lastUsed).toLocaleDateString()}
                                  </span>
                                )}
                              </div>
                            </div>
                            <button
                              type="button"
                              onClick={() => revokeAPIKey(apiKey.id)}
                              className="p-1.5 rounded transition-all duration-150 mt-0.5"
                              style={{ color: 'var(--stash-text-secondary)' }}
                              onMouseEnter={(e) => {
                                e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                              }}
                              onMouseLeave={(e) => {
                                e.currentTarget.style.backgroundColor = 'transparent';
                              }}
                              title="Revoke API Key"
                            >
                              <Trash2 className="w-3.5 h-3.5" style={{ color: 'var(--stash-error)' }} />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Divider */}
                <div style={{ borderTop: '1px solid var(--stash-border)' }} />
              </>
            )}

            {/* Content Roots Section */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3
                  className="text-sm font-semibold"
                  style={{ color: 'var(--stash-text-bright)' }}
                >
                  Content Roots
                </h3>
                <button
                  type="button"
                  onClick={addContentRoot}
                  className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs transition-all duration-150"
                  style={{
                    backgroundColor: 'var(--stash-bg-base)',
                    color: 'var(--stash-accent)',
                    border: '1px solid var(--stash-accent)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'var(--stash-bg-base)';
                  }}
                >
                  <Plus className="w-3 h-3" />
                  Add Content Root
                </button>
              </div>
              <p className="text-xs mb-4" style={{ color: 'var(--stash-text-secondary)' }}>
                Define which directories this server can access
              </p>

              <div className="space-y-4">
                {contentRoots.length === 0 ? (
                  <div
                    className="p-4 rounded-md text-center text-sm"
                    style={{
                      backgroundColor: 'var(--stash-bg-base)',
                      color: 'var(--stash-text-secondary)',
                      border: '1px dashed var(--stash-border)',
                    }}
                  >
                    No content roots yet. Click "Add Content Root" to get started.
                  </div>
                ) : (
                  contentRoots.map((contentRoot) => (
                    <div
                      key={contentRoot.id}
                      className="p-4 rounded-md border"
                      style={{
                        backgroundColor: 'var(--stash-bg-base)',
                        borderColor: 'var(--stash-border)',
                      }}
                    >
                      <div className="flex items-start justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <FolderTree
                            className="w-4 h-4"
                            style={{ color: 'var(--stash-accent)' }}
                          />
                          <span
                            className="text-xs font-medium"
                            style={{ color: 'var(--stash-text-bright)' }}
                          >
                            Content Root
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => removeContentRoot(contentRoot.id)}
                          className="p-1 rounded transition-all duration-150"
                          style={{ color: 'var(--stash-text-secondary)' }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.backgroundColor = 'transparent';
                          }}
                        >
                          <Trash2 className="w-4 h-4" style={{ color: 'var(--stash-error)' }} />
                        </button>
                      </div>

                      <div className="space-y-3">
                        {/* Name */}
                        <input
                          type="text"
                          value={contentRoot.name}
                          onChange={(e) =>
                            updateContentRoot(contentRoot.id, { name: e.target.value })
                          }
                          placeholder="Content root name"
                          className="w-full px-3 py-2 rounded-md text-sm outline-none transition-all duration-150"
                          style={{
                            backgroundColor: 'var(--stash-bg-surface)',
                            color: 'var(--stash-text-primary)',
                            border: '1px solid var(--stash-border)',
                          }}
                          onFocus={(e) => {
                            e.currentTarget.style.borderColor = 'var(--stash-accent)';
                            e.currentTarget.style.boxShadow = '0 0 0 2px rgba(148, 226, 213, 0.1)';
                          }}
                          onBlur={(e) => {
                            e.currentTarget.style.borderColor = 'var(--stash-border)';
                            e.currentTarget.style.boxShadow = 'none';
                          }}
                        />

                        {/* Description */}
                        <input
                          type="text"
                          value={contentRoot.description}
                          onChange={(e) =>
                            updateContentRoot(contentRoot.id, { description: e.target.value })
                          }
                          placeholder="Description (optional)"
                          className="w-full px-3 py-2 rounded-md text-sm outline-none transition-all duration-150"
                          style={{
                            backgroundColor: 'var(--stash-bg-surface)',
                            color: 'var(--stash-text-primary)',
                            border: '1px solid var(--stash-border)',
                          }}
                          onFocus={(e) => {
                            e.currentTarget.style.borderColor = 'var(--stash-accent)';
                            e.currentTarget.style.boxShadow = '0 0 0 2px rgba(148, 226, 213, 0.1)';
                          }}
                          onBlur={(e) => {
                            e.currentTarget.style.borderColor = 'var(--stash-border)';
                            e.currentTarget.style.boxShadow = 'none';
                          }}
                        />

                        {/* Type Selection */}
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            type="button"
                            onClick={() => updateContentRoot(contentRoot.id, { type: 'simple' })}
                            className="px-3 py-2 rounded-md text-xs transition-all duration-150"
                            style={{
                              backgroundColor:
                                contentRoot.type === 'simple'
                                  ? 'var(--stash-accent)'
                                  : 'var(--stash-bg-surface)',
                              color:
                                contentRoot.type === 'simple'
                                  ? 'var(--stash-bg-base)'
                                  : 'var(--stash-text-primary)',
                              border: '1px solid var(--stash-border)',
                            }}
                            onMouseEnter={(e) => {
                              if (contentRoot.type !== 'simple') {
                                e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                              }
                            }}
                            onMouseLeave={(e) => {
                              if (contentRoot.type !== 'simple') {
                                e.currentTarget.style.backgroundColor = 'var(--stash-bg-surface)';
                              }
                            }}
                          >
                            Simple Directory
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              updateContentRoot(contentRoot.id, { type: 'virtual', mountedDirectories: [] })
                            }
                            className="px-3 py-2 rounded-md text-xs transition-all duration-150"
                            style={{
                              backgroundColor:
                                contentRoot.type === 'virtual'
                                  ? 'var(--stash-accent)'
                                  : 'var(--stash-bg-surface)',
                              color:
                                contentRoot.type === 'virtual'
                                  ? 'var(--stash-bg-base)'
                                  : 'var(--stash-text-primary)',
                              border: '1px solid var(--stash-border)',
                            }}
                            onMouseEnter={(e) => {
                              if (contentRoot.type !== 'virtual') {
                                e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                              }
                            }}
                            onMouseLeave={(e) => {
                              if (contentRoot.type !== 'virtual') {
                                e.currentTarget.style.backgroundColor = 'var(--stash-bg-surface)';
                              }
                            }}
                          >
                            Virtual Content Root
                          </button>
                        </div>

                        {/* Simple Directory Path */}
                        {contentRoot.type === 'simple' && (
                          <input
                            type="text"
                            value={contentRoot.path || ''}
                            onChange={(e) =>
                              updateContentRoot(contentRoot.id, { path: e.target.value })
                            }
                            placeholder="e.g., /home/user/documents"
                            className="w-full px-3 py-2 rounded-md text-sm outline-none transition-all duration-150"
                            style={{
                              backgroundColor: 'var(--stash-bg-surface)',
                              color: 'var(--stash-text-primary)',
                              border: '1px solid var(--stash-border)',
                            }}
                            onFocus={(e) => {
                              e.currentTarget.style.borderColor = 'var(--stash-accent)';
                              e.currentTarget.style.boxShadow = '0 0 0 2px rgba(148, 226, 213, 0.1)';
                            }}
                            onBlur={(e) => {
                              e.currentTarget.style.borderColor = 'var(--stash-border)';
                              e.currentTarget.style.boxShadow = 'none';
                            }}
                          />
                        )}

                        {/* Virtual Content Root - Mounted Directories */}
                        {contentRoot.type === 'virtual' && (
                          <div>
                            <div className="flex items-center justify-between mb-2">
                              <label
                                className="text-xs font-medium"
                                style={{ color: 'var(--stash-text-primary)' }}
                              >
                                Mounted Directories
                              </label>
                              <button
                                type="button"
                                onClick={() => addMountedDirectory(contentRoot.id)}
                                className="flex items-center gap-1 px-2 py-1 rounded-md text-xs transition-all duration-150"
                                style={{
                                  backgroundColor: 'var(--stash-bg-surface)',
                                  color: 'var(--stash-accent)',
                                  border: '1px solid var(--stash-border)',
                                }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.backgroundColor = 'var(--stash-bg-surface)';
                                }}
                              >
                                <Plus className="w-3 h-3" />
                                Add Directory
                              </button>
                            </div>

                            <div className="space-y-2">
                              {contentRoot.mountedDirectories?.map((mount) => (
                                <div
                                  key={mount.id}
                                  className="flex items-center gap-2 p-2 rounded-md"
                                  style={{
                                    backgroundColor: 'var(--stash-bg-surface)',
                                    border: '1px solid var(--stash-border)',
                                  }}
                                >
                                  <input
                                    type="text"
                                    value={mount.path}
                                    onChange={(e) =>
                                      updateMountedDirectory(contentRoot.id, mount.id, {
                                        path: e.target.value,
                                      })
                                    }
                                    placeholder="Directory path"
                                    className="flex-1 px-2 py-1.5 rounded-md text-xs outline-none transition-all duration-150"
                                    style={{
                                      backgroundColor: 'var(--stash-bg-base)',
                                      color: 'var(--stash-text-primary)',
                                      border: '1px solid var(--stash-border)',
                                    }}
                                    onFocus={(e) => {
                                      e.currentTarget.style.borderColor = 'var(--stash-accent)';
                                      e.currentTarget.style.boxShadow =
                                        '0 0 0 1px rgba(148, 226, 213, 0.1)';
                                    }}
                                    onBlur={(e) => {
                                      e.currentTarget.style.borderColor = 'var(--stash-border)';
                                      e.currentTarget.style.boxShadow = 'none';
                                    }}
                                  />
                                  <div className="flex gap-1">
                                    <button
                                      type="button"
                                      onClick={() =>
                                        updateMountedDirectory(contentRoot.id, mount.id, {
                                          permission: 'read',
                                        })
                                      }
                                      className="px-2 py-1.5 rounded-md text-xs transition-all duration-150"
                                      style={{
                                        backgroundColor:
                                          mount.permission === 'read'
                                            ? 'var(--stash-accent)'
                                            : 'var(--stash-bg-base)',
                                        color:
                                          mount.permission === 'read'
                                            ? 'var(--stash-bg-base)'
                                            : 'var(--stash-text-secondary)',
                                        border: '1px solid var(--stash-border)',
                                      }}
                                      title="Read Only"
                                    >
                                      <Lock className="w-3 h-3" />
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() =>
                                        updateMountedDirectory(contentRoot.id, mount.id, {
                                          permission: 'read-write',
                                        })
                                      }
                                      className="px-2 py-1.5 rounded-md text-xs transition-all duration-150"
                                      style={{
                                        backgroundColor:
                                          mount.permission === 'read-write'
                                            ? 'var(--stash-accent)'
                                            : 'var(--stash-bg-base)',
                                        color:
                                          mount.permission === 'read-write'
                                            ? 'var(--stash-bg-base)'
                                            : 'var(--stash-text-secondary)',
                                        border: '1px solid var(--stash-border)',
                                      }}
                                      title="Read-Write"
                                    >
                                      <LockOpen className="w-3 h-3" />
                                    </button>
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => removeMountedDirectory(contentRoot.id, mount.id)}
                                    className="p-1.5 rounded transition-all duration-150"
                                    style={{ color: 'var(--stash-text-secondary)' }}
                                    onMouseEnter={(e) => {
                                      e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                                    }}
                                    onMouseLeave={(e) => {
                                      e.currentTarget.style.backgroundColor = 'transparent';
                                    }}
                                  >
                                    <Trash2
                                      className="w-3.5 h-3.5"
                                      style={{ color: 'var(--stash-error)' }}
                                    />
                                  </button>
                                </div>
                              ))}

                              {(!contentRoot.mountedDirectories ||
                                contentRoot.mountedDirectories.length === 0) && (
                                <div
                                  className="p-3 rounded-md text-center text-xs"
                                  style={{
                                    backgroundColor: 'var(--stash-bg-surface)',
                                    color: 'var(--stash-text-secondary)',
                                    border: '1px dashed var(--stash-border)',
                                  }}
                                >
                                  No mounted directories yet
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </form>

        {/* Footer */}
        <div
          className="flex items-center justify-end gap-3 px-6 py-4 border-t"
          style={{ borderColor: 'var(--stash-border)' }}
        >
          <button
            type="button"
            onClick={handleClose}
            className="px-4 py-2 rounded-md text-sm transition-all duration-150"
            style={{
              backgroundColor: 'var(--stash-bg-base)',
              color: 'var(--stash-text-primary)',
              border: '1px solid var(--stash-border)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-base)';
            }}
          >
            Cancel
          </button>
          <button
            type="submit"
            onClick={handleSubmit}
            className="px-4 py-2 rounded-md text-sm transition-all duration-150"
            style={{
              backgroundColor: 'var(--stash-accent)',
              color: 'var(--stash-bg-base)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.opacity = '0.9';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = '1';
            }}
          >
            {editingServer ? 'Update Server' : 'Create Server'}
          </button>
        </div>
      </div>
    </div>
  );
}