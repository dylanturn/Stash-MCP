import React, { useState, useEffect, useRef } from 'react';
import * as yaml from 'js-yaml';
import { ChevronDown, ChevronRight, Server, MessageSquare, Zap, Info } from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

interface AsyncApiViewerProps {
  content: string;
  onSectionsChange?: (sections: Array<{ id: string; title: string; color?: string }>) => void;
  onActiveSectionChange?: (id: string | null) => void;
}

export function AsyncApiViewer({ content, onSectionsChange, onActiveSectionChange }: AsyncApiViewerProps) {
  const [error, setError] = useState<string | null>(null);
  const [spec, setSpec] = useState<any>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(['info', 'servers', 'channels'])
  );
  const [activeSection, setActiveSection] = useState<string | null>('info');
  const sectionRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // Notify parent of available sections when spec changes
  useEffect(() => {
    if (!spec || !onSectionsChange) return;

    const sections = [];
    if (spec.info) sections.push({ id: 'info', title: 'Info', color: 'var(--stash-accent)' });
    if (spec.servers && Object.keys(spec.servers).length > 0) {
      sections.push({ id: 'servers', title: 'Servers', color: '#89b4fa' });
    }
    if (spec.channels && Object.keys(spec.channels).length > 0) {
      sections.push({ id: 'channels', title: 'Channels', color: 'var(--stash-accent)' });
    }
    if (spec.operations && Object.keys(spec.operations).length > 0) {
      sections.push({ id: 'operations', title: 'Operations', color: '#a6e3a1' });
    }
    if (spec.components?.schemas && Object.keys(spec.components.schemas).length > 0) {
      sections.push({ id: 'schemas', title: 'Schemas', color: '#cba6f7' });
    }

    onSectionsChange(sections);
  }, [spec, onSectionsChange]);

  useEffect(() => {
    try {
      // Try to parse as JSON first
      let specObj;
      try {
        specObj = JSON.parse(content);
      } catch {
        // If JSON parse fails, try YAML
        specObj = yaml.load(content);
      }

      // Validate it's an AsyncAPI spec
      if (!specObj.asyncapi) {
        setError('Not a valid AsyncAPI specification (missing asyncapi field)');
        return;
      }

      setSpec(specObj);
      setError(null);
    } catch (e) {
      console.error('Failed to parse AsyncAPI spec:', e);
      setError('Invalid AsyncAPI specification format');
    }
  }, [content]);

  const toggleSection = (section: string) => {
    const newExpanded = new Set(expandedSections);
    if (newExpanded.has(section)) {
      newExpanded.delete(section);
    } else {
      newExpanded.add(section);
    }
    setExpandedSections(newExpanded);
    if (onActiveSectionChange) {
      onActiveSectionChange(section);
    }
  };

  const renderBadge = (text: string, color: string) => (
    <span
      className="px-2 py-1 rounded text-xs font-semibold"
      style={{ backgroundColor: color, color: 'var(--stash-bg-base)' }}
    >
      {text}
    </span>
  );

  const renderCodeBlock = (code: any) => (
    <SyntaxHighlighter
      language="json"
      style={vscDarkPlus}
      customStyle={{
        backgroundColor: 'var(--stash-bg-base)',
        border: '1px solid var(--stash-border)',
        borderRadius: '6px',
        fontSize: '0.875rem',
      }}
    >
      {JSON.stringify(code, null, 2)}
    </SyntaxHighlighter>
  );

  const renderSchema = (schema: any, name?: string) => {
    if (!schema) return null;

    return (
      <div
        className="p-4 rounded mb-3"
        style={{
          backgroundColor: 'var(--stash-bg-surface)',
          border: '1px solid var(--stash-border)',
        }}
      >
        {name && (
          <h5 className="mb-2" style={{ color: 'var(--stash-text-bright)' }}>
            {name}
          </h5>
        )}
        {schema.type && (
          <div className="mb-2">
            <span style={{ color: 'var(--stash-text-muted)' }}>Type: </span>
            <code
              className="px-2 py-1 rounded text-sm"
              style={{ backgroundColor: 'var(--stash-bg-base)', color: 'var(--stash-accent)' }}
            >
              {schema.type}
            </code>
          </div>
        )}
        {schema.description && (
          <p className="mb-2 text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
            {schema.description}
          </p>
        )}
        {schema.properties && (
          <div className="mt-3">
            <h6 className="mb-2 text-sm" style={{ color: 'var(--stash-text-bright)' }}>
              Properties:
            </h6>
            <div className="space-y-2">
              {Object.entries(schema.properties).map(([propName, propSchema]: [string, any]) => (
                <div
                  key={propName}
                  className="p-3 rounded"
                  style={{
                    backgroundColor: 'var(--stash-bg-base)',
                    borderLeft: '3px solid var(--stash-accent)',
                  }}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span style={{ color: 'var(--stash-text-bright)' }}>{propName}</span>
                    {propSchema.type && (
                      <code
                        className="px-2 py-0.5 rounded text-xs"
                        style={{
                          backgroundColor: 'rgba(148, 226, 213, 0.2)',
                          color: 'var(--stash-accent)',
                        }}
                      >
                        {propSchema.type}
                      </code>
                    )}
                    {schema.required?.includes(propName) && renderBadge('required', '#f38ba8')}
                  </div>
                  {propSchema.description && (
                    <p className="text-sm" style={{ color: 'var(--stash-text-muted)' }}>
                      {propSchema.description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
        {schema.enum && (
          <div className="mt-2">
            <span style={{ color: 'var(--stash-text-muted)' }}>Enum: </span>
            <div className="inline-flex flex-wrap gap-2">
              {schema.enum.map((val: any, idx: number) => (
                <code
                  key={idx}
                  className="px-2 py-1 rounded text-sm"
                  style={{ backgroundColor: 'var(--stash-bg-base)', color: 'var(--stash-accent)' }}
                >
                  {String(val)}
                </code>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  if (error) {
    return (
      <div className="h-full w-full flex items-center justify-center p-8" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <div className="text-center">
          <p style={{ color: 'var(--stash-error)' }} className="mb-2">
            {error}
          </p>
          <p style={{ color: 'var(--stash-text-secondary)' }} className="text-sm">
            Please check that the file contains a valid AsyncAPI 2.x or 3.x specification
          </p>
        </div>
      </div>
    );
  }

  if (!spec) {
    return (
      <div className="h-full w-full flex items-center justify-center" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <p style={{ color: 'var(--stash-text-secondary)' }}>Loading AsyncAPI documentation...</p>
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-auto p-8" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
      {/* Info Section */}
      {spec.info && (
        <div className="mb-8 pb-6" style={{ borderBottom: '1px solid var(--stash-border)' }}>
          <div className="flex items-center gap-3 mb-3">
            <Info className="w-8 h-8" style={{ color: 'var(--stash-accent)' }} />
            <h1 className="text-3xl" style={{ color: 'var(--stash-text-bright)' }}>
              {spec.info.title}
            </h1>
            {spec.info.version && renderBadge(`v${spec.info.version}`, 'var(--stash-accent)')}
            {spec.asyncapi && (
              <span
                className="px-2 py-1 rounded text-xs"
                style={{
                  backgroundColor: 'rgba(137, 180, 250, 0.2)',
                  color: '#89b4fa',
                }}
              >
                AsyncAPI {spec.asyncapi}
              </span>
            )}
          </div>
          {spec.info.description && (
            <p className="text-base mb-3" style={{ color: 'var(--stash-text-secondary)' }}>
              {spec.info.description}
            </p>
          )}
          {spec.info.contact && (
            <div className="flex gap-4 text-sm" style={{ color: 'var(--stash-text-muted)' }}>
              {spec.info.contact.name && <span key="contact-name">Contact: {spec.info.contact.name}</span>}
              {spec.info.contact.email && <span key="contact-email">Email: {spec.info.contact.email}</span>}
            </div>
          )}
        </div>
      )}

      {/* Servers Section */}
      {spec.servers && Object.keys(spec.servers).length > 0 && (
        <div className="mb-6">
          <button
            onClick={() => toggleSection('servers')}
            className="flex items-center gap-2 mb-4"
          >
            {expandedSections.has('servers') ? (
              <ChevronDown className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
            ) : (
              <ChevronRight className="w-5 h-5" style={{ color: 'var(--stash-text-muted)' }} />
            )}
            <Server className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
            <h2 className="text-xl" style={{ color: 'var(--stash-text-bright)' }}>
              Servers
            </h2>
          </button>
          {expandedSections.has('servers') && (
            <div className="ml-7 space-y-3">
              {Object.entries(spec.servers).map(([serverName, server]: [string, any]) => (
                <div
                  key={serverName}
                  className="p-4 rounded"
                  style={{
                    backgroundColor: 'var(--stash-bg-surface)',
                    border: '1px solid var(--stash-border)',
                  }}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <h3 style={{ color: 'var(--stash-text-bright)' }}>{serverName}</h3>
                    {server.protocol && renderBadge(server.protocol, '#89b4fa')}
                  </div>
                  {server.url && (
                    <code
                      className="block px-3 py-2 rounded text-sm mb-2"
                      style={{
                        backgroundColor: 'var(--stash-bg-base)',
                        color: 'var(--stash-accent)',
                      }}
                    >
                      {server.url || server.host}
                    </code>
                  )}
                  {server.description && (
                    <p className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
                      {server.description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Channels Section */}
      {spec.channels && Object.keys(spec.channels).length > 0 && (
        <div className="mb-6">
          <button
            onClick={() => toggleSection('channels')}
            className="flex items-center gap-2 mb-4"
          >
            {expandedSections.has('channels') ? (
              <ChevronDown className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
            ) : (
              <ChevronRight className="w-5 h-5" style={{ color: 'var(--stash-text-muted)' }} />
            )}
            <MessageSquare className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
            <h2 className="text-xl" style={{ color: 'var(--stash-text-bright)' }}>
              Channels
            </h2>
          </button>
          {expandedSections.has('channels') && (
            <div className="ml-7 space-y-4">
              {Object.entries(spec.channels).map(([channelPath, channel]: [string, any]) => (
                <div
                  key={channelPath}
                  className="p-4 rounded"
                  style={{
                    backgroundColor: 'var(--stash-bg-surface)',
                    border: '1px solid var(--stash-border)',
                    borderLeft: '3px solid var(--stash-accent)',
                  }}
                >
                  <h3 className="mb-2" style={{ color: 'var(--stash-text-bright)' }}>
                    {channel.address || channelPath}
                  </h3>
                  {channel.description && (
                    <p className="mb-3 text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
                      {channel.description}
                    </p>
                  )}
                  {channel.messages && (
                    <div className="mt-3">
                      <h4 className="text-sm mb-2" style={{ color: 'var(--stash-text-bright)' }}>
                        Messages:
                      </h4>
                      {Object.entries(channel.messages).map(([msgKey, msgRef]: [string, any]) => {
                        const message = msgRef.$ref
                          ? spec.components?.messages?.[msgRef.$ref.split('/').pop()]
                          : msgRef;
                        return (
                          <div
                            key={msgKey}
                            className="p-3 rounded mb-2"
                            style={{ backgroundColor: 'var(--stash-bg-base)' }}
                          >
                            {message?.name && (
                              <h5 className="mb-1" style={{ color: 'var(--stash-text-bright)' }}>
                                {message.name}
                              </h5>
                            )}
                            {message?.summary && (
                              <p className="text-sm mb-2" style={{ color: 'var(--stash-text-muted)' }}>
                                {message.summary}
                              </p>
                            )}
                            {message?.payload && renderSchema(message.payload, 'Payload')}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Operations Section */}
      {spec.operations && Object.keys(spec.operations).length > 0 && (
        <div className="mb-6">
          <button
            onClick={() => toggleSection('operations')}
            className="flex items-center gap-2 mb-4"
          >
            {expandedSections.has('operations') ? (
              <ChevronDown className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
            ) : (
              <ChevronRight className="w-5 h-5" style={{ color: 'var(--stash-text-muted)' }} />
            )}
            <Zap className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
            <h2 className="text-xl" style={{ color: 'var(--stash-text-bright)' }}>
              Operations
            </h2>
          </button>
          {expandedSections.has('operations') && (
            <div className="ml-7 space-y-3">
              {Object.entries(spec.operations).map(([opId, operation]: [string, any]) => (
                <div
                  key={opId}
                  className="p-4 rounded"
                  style={{
                    backgroundColor: 'var(--stash-bg-surface)',
                    border: '1px solid var(--stash-border)',
                    borderLeft: `3px solid ${operation.action === 'send' ? '#a6e3a1' : '#89b4fa'}`,
                  }}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <h3 style={{ color: 'var(--stash-text-bright)' }}>{opId}</h3>
                    {operation.action &&
                      renderBadge(operation.action, operation.action === 'send' ? '#a6e3a1' : '#89b4fa')}
                  </div>
                  {operation.summary && (
                    <p className="mb-2 text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
                      {operation.summary}
                    </p>
                  )}
                  {operation.description && (
                    <p className="text-sm" style={{ color: 'var(--stash-text-muted)' }}>
                      {operation.description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Components/Schemas Section */}
      {spec.components?.schemas && Object.keys(spec.components.schemas).length > 0 && (
        <div className="mb-6">
          <button
            onClick={() => toggleSection('schemas')}
            className="flex items-center gap-2 mb-4"
          >
            {expandedSections.has('schemas') ? (
              <ChevronDown className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
            ) : (
              <ChevronRight className="w-5 h-5" style={{ color: 'var(--stash-text-muted)' }} />
            )}
            <h2 className="text-xl" style={{ color: 'var(--stash-text-bright)' }}>
              Schemas
            </h2>
          </button>
          {expandedSections.has('schemas') && (
            <div className="ml-7 space-y-3">
              {Object.entries(spec.components.schemas).map(([schemaName, schema]: [string, any]) => (
                <React.Fragment key={schemaName}>
                  {renderSchema(schema, schemaName)}
                </React.Fragment>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}