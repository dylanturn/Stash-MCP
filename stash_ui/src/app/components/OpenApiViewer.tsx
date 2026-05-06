import React, { useState, useEffect, useRef } from 'react';
import { ChevronDown, ChevronRight, Globe, Server, Code, Copy, Check, BookOpen, Tag, FileJson, List, X } from 'lucide-react';

interface OpenApiViewerProps {
  spec: string;
  onEndpointsChange?: (endpoints: Array<{ id: string; method: string; path: string; summary?: string }>) => void;
  onActiveEndpointChange?: (id: string | null) => void;
}

interface Method {
  method: string;
  path: string;
  summary?: string;
  description?: string;
  tags?: string[];
  parameters?: any[];
  requestBody?: any;
  responses?: any;
  operationId?: string;
}

export function OpenApiViewer({ spec, onEndpointsChange, onActiveEndpointChange }: OpenApiViewerProps) {
  const [error, setError] = useState<string | null>(null);
  const [apiSpec, setApiSpec] = useState<any>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['info']));
  const [expandedEndpoints, setExpandedEndpoints] = useState<Set<string>>(new Set());
  const [selectedTag, setSelectedTag] = useState<string>('all');
  const [copiedItem, setCopiedItem] = useState<string | null>(null);
  const [activeEndpoint, setActiveEndpoint] = useState<string | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const endpointRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  useEffect(() => {
    try {
      const parsedSpec = JSON.parse(spec);
      setApiSpec(parsedSpec);
      setError(null);
    } catch (e) {
      console.error('Failed to parse OpenAPI spec:', e);
      setError('Invalid OpenAPI specification format');
    }
  }, [spec]);

  const toggleSection = (section: string) => {
    const newExpanded = new Set(expandedSections);
    if (newExpanded.has(section)) {
      newExpanded.delete(section);
    } else {
      newExpanded.add(section);
    }
    setExpandedSections(newExpanded);
  };

  const toggleEndpoint = (endpointId: string) => {
    const newExpanded = new Set(expandedEndpoints);
    if (newExpanded.has(endpointId)) {
      newExpanded.delete(endpointId);
    } else {
      newExpanded.add(endpointId);
    }
    setExpandedEndpoints(newExpanded);
  };

  const copyToClipboard = (text: string, itemId: string) => {
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          setCopiedItem(itemId);
          setTimeout(() => setCopiedItem(null), 2000);
        }).catch(() => {
          fallbackCopy(text, itemId);
        });
      } else {
        fallbackCopy(text, itemId);
      }
    } catch (err) {
      fallbackCopy(text, itemId);
    }
  };

  const fallbackCopy = (text: string, itemId: string) => {
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

  const getMethodColor = (method: string) => {
    const colors: { [key: string]: { bg: string; border: string; text: string; badge: string } } = {
      get: { bg: 'rgba(148, 226, 213, 0.1)', border: '#94e2d5', text: '#94e2d5', badge: '#94e2d5' },
      post: { bg: 'rgba(166, 227, 161, 0.1)', border: '#a6e3a1', text: '#a6e3a1', badge: '#a6e3a1' },
      put: { bg: 'rgba(249, 226, 175, 0.1)', border: '#f9e2af', text: '#f9e2af', badge: '#f9e2af' },
      patch: { bg: 'rgba(203, 166, 247, 0.1)', border: '#cba6f7', text: '#cba6f7', badge: '#cba6f7' },
      delete: { bg: 'rgba(243, 139, 168, 0.1)', border: '#f38ba8', text: '#f38ba8', badge: '#f38ba8' },
    };
    return colors[method.toLowerCase()] || colors.get;
  };

  const collectAllMethods = (): Method[] => {
    if (!apiSpec?.paths) return [];
    
    const methods: Method[] = [];
    Object.entries(apiSpec.paths).forEach(([path, pathItem]: [string, any]) => {
      ['get', 'post', 'put', 'patch', 'delete', 'options', 'head'].forEach((method) => {
        if (pathItem[method]) {
          methods.push({
            method,
            path,
            ...pathItem[method]
          });
        }
      });
    });
    
    return methods;
  };

  const getAllTags = (): string[] => {
    const tags = new Set<string>();
    collectAllMethods().forEach(method => {
      method.tags?.forEach(tag => tags.add(tag));
    });
    return Array.from(tags).sort();
  };

  const getFilteredMethods = (): Method[] => {
    const allMethods = collectAllMethods();
    if (selectedTag === 'all') return allMethods;
    return allMethods.filter(m => m.tags?.includes(selectedTag));
  };

  const scrollToEndpoint = (endpointId: string) => {
    const element = endpointRefs.current.get(endpointId);
    if (element) {
      const yOffset = -80; // Offset for header
      const y = element.getBoundingClientRect().top + window.pageYOffset + yOffset;
      window.scrollTo({ top: y, behavior: 'smooth' });
    }
  };

  // Set up intersection observer for scrollspy
  useEffect(() => {
    if (!apiSpec) return;

    const observer = new IntersectionObserver(
      (entries) => {
        // Find all visible endpoints
        const visibleEndpoints = entries
          .filter(entry => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);

        if (visibleEndpoints.length > 0) {
          const firstVisible = visibleEndpoints[0].target.getAttribute('data-endpoint-id');
          if (firstVisible) {
            setActiveEndpoint(firstVisible);
            onActiveEndpointChange?.(firstVisible);
          }
        }
      },
      {
        root: null,
        rootMargin: '-100px 0px -60% 0px',
        threshold: [0, 0.25, 0.5, 0.75, 1]
      }
    );

    // Observe all endpoint elements after a short delay
    const timeoutId = setTimeout(() => {
      endpointRefs.current.forEach((element) => {
        if (element) observer.observe(element);
      });
    }, 100);

    return () => {
      clearTimeout(timeoutId);
      observer.disconnect();
    };
  }, [apiSpec, selectedTag]); // Changed from filteredMethods to selectedTag

  // Notify parent of endpoints changes
  useEffect(() => {
    if (!apiSpec) return;
    
    const filteredMethods = getFilteredMethods();
    if (onEndpointsChange) {
      onEndpointsChange(filteredMethods.map(method => ({
        id: `${method.method}-${method.path}`,
        method: method.method,
        path: method.path,
        summary: method.summary
      })));
    }
  }, [apiSpec, selectedTag, onEndpointsChange]);

  const renderSchema = (schema: any, name?: string): React.ReactNode => {
    if (!schema) return null;

    if (schema.$ref) {
      const refName = schema.$ref.split('/').pop();
      return (
        <span className="text-sm" style={{ color: 'var(--stash-accent)', fontFamily: 'monospace' }}>
          {refName}
        </span>
      );
    }

    if (schema.type === 'object' && schema.properties) {
      return (
        <div className="ml-4 mt-2">
          {Object.entries(schema.properties).map(([propName, propSchema]: [string, any]) => (
            <div key={propName} className="mb-2">
              <div className="flex items-start gap-2">
                <code 
                  className="text-sm px-2 py-0.5 rounded"
                  style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)' }}
                >
                  {propName}
                </code>
                <span className="text-xs" style={{ color: 'var(--stash-text-muted)' }}>
                  {propSchema.type}
                  {schema.required?.includes(propName) && (
                    <span className="ml-2 text-xs" style={{ color: '#f38ba8' }}>required</span>
                  )}
                </span>
              </div>
              {propSchema.description && (
                <p className="text-xs mt-1 ml-2" style={{ color: 'var(--stash-text-secondary)' }}>
                  {propSchema.description}
                </p>
              )}
              {propSchema.example !== undefined && (
                <code className="text-xs block mt-1 ml-2" style={{ color: 'var(--stash-text-muted)' }}>
                  Example: {JSON.stringify(propSchema.example)}
                </code>
              )}
            </div>
          ))}
        </div>
      );
    }

    if (schema.type === 'array' && schema.items) {
      return (
        <div>
          <span className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>Array of:</span>
          {renderSchema(schema.items)}
        </div>
      );
    }

    return (
      <span className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
        {schema.type}
        {schema.enum && ` (${schema.enum.join(' | ')})`}
      </span>
    );
  };

  const renderEndpoint = (method: Method) => {
    const endpointId = `${method.method}-${method.path}`;
    const isExpanded = expandedEndpoints.has(endpointId);
    const colors = getMethodColor(method.method);

    return (
      <div
        key={endpointId}
        ref={(el) => {
          if (el) endpointRefs.current.set(endpointId, el);
        }}
        data-endpoint-id={endpointId}
        className="mb-3 rounded-lg overflow-hidden transition-all duration-150 scroll-mt-20"
        style={{ 
          backgroundColor: colors.bg,
          border: `1px solid ${colors.border}`
        }}
      >
        <div className="flex items-stretch">
          <button
            onClick={() => toggleEndpoint(endpointId)}
            className="flex-1 p-4 flex items-center gap-3 transition-all duration-150"
            onMouseEnter={(e) => {
              e.currentTarget.parentElement!.style.backgroundColor = 'rgba(255, 255, 255, 0.05)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.parentElement!.style.backgroundColor = 'transparent';
            }}
          >
            {isExpanded ? (
              <ChevronDown className="w-5 h-5" style={{ color: colors.text }} />
            ) : (
              <ChevronRight className="w-5 h-5" style={{ color: 'var(--stash-text-muted)' }} />
            )}
            
            <span 
              className="px-3 py-1 rounded text-xs font-bold uppercase"
              style={{ 
                backgroundColor: colors.badge,
                color: 'var(--stash-bg-base)',
                minWidth: '70px',
                textAlign: 'center'
              }}
            >
              {method.method}
            </span>
            
            <code 
              className="font-mono text-sm flex-1 text-left"
              style={{ color: 'var(--stash-text-bright)' }}
            >
              {method.path}
            </code>

            {method.summary && (
              <span className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
                {method.summary}
              </span>
            )}
          </button>

          <button
            onClick={(e) => {
              e.stopPropagation();
              copyToClipboard(method.path, endpointId);
            }}
            className="p-4 rounded transition-all duration-150"
            style={{ color: 'var(--stash-text-muted)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.05)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
            title="Copy path"
          >
            {copiedItem === endpointId ? (
              <Check className="w-4 h-4" style={{ color: 'var(--stash-accent)' }} />
            ) : (
              <Copy className="w-4 h-4" />
            )}
          </button>
        </div>

        {isExpanded && (
          <div className="px-4 pb-4 pt-2 space-y-4" style={{ backgroundColor: 'var(--stash-bg-surface)' }}>
            {method.description && (
              <div>
                <h5 className="text-sm mb-2" style={{ color: 'var(--stash-text-bright)' }}>Description</h5>
                <p className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
                  {method.description}
                </p>
              </div>
            )}

            {method.parameters && method.parameters.length > 0 && (
              <div>
                <h5 className="text-sm mb-3" style={{ color: 'var(--stash-text-bright)' }}>Parameters</h5>
                <div className="space-y-2">
                  {method.parameters.map((param: any, idx: number) => (
                    <div 
                      key={idx}
                      className="p-3 rounded"
                      style={{ backgroundColor: 'var(--stash-bg-base)' }}
                    >
                      <div className="flex items-center gap-2 mb-1">
                        <code 
                          className="text-sm px-2 py-0.5 rounded"
                          style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)' }}
                        >
                          {param.name}
                        </code>
                        <span 
                          className="text-xs px-2 py-0.5 rounded"
                          style={{ 
                            backgroundColor: 'rgba(137, 180, 250, 0.2)',
                            color: '#89b4fa'
                          }}
                        >
                          {param.in}
                        </span>
                        {param.required && (
                          <span 
                            className="text-xs px-2 py-0.5 rounded"
                            style={{ 
                              backgroundColor: 'rgba(243, 139, 168, 0.2)',
                              color: '#f38ba8'
                            }}
                          >
                            required
                          </span>
                        )}
                      </div>
                      {param.description && (
                        <p className="text-sm mt-1" style={{ color: 'var(--stash-text-secondary)' }}>
                          {param.description}
                        </p>
                      )}
                      {param.schema && (
                        <div className="text-xs mt-2" style={{ color: 'var(--stash-text-muted)' }}>
                          Type: {param.schema.type}
                          {param.schema.default !== undefined && ` (default: ${param.schema.default})`}
                          {param.schema.maximum !== undefined && ` (max: ${param.schema.maximum})`}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {method.requestBody && (
              <div>
                <h5 className="text-sm mb-3" style={{ color: 'var(--stash-text-bright)' }}>Request Body</h5>
                <div 
                  className="p-3 rounded"
                  style={{ backgroundColor: 'var(--stash-bg-base)' }}
                >
                  {method.requestBody.required && (
                    <span 
                      className="text-xs px-2 py-0.5 rounded mb-2 inline-block"
                      style={{ 
                        backgroundColor: 'rgba(243, 139, 168, 0.2)',
                        color: '#f38ba8'
                      }}
                    >
                      required
                    </span>
                  )}
                  {method.requestBody.content && Object.entries(method.requestBody.content).map(([contentType, content]: [string, any]) => (
                    <div key={contentType}>
                      <div className="text-xs mb-2" style={{ color: 'var(--stash-text-muted)' }}>
                        Content-Type: {contentType}
                      </div>
                      {content.schema && renderSchema(content.schema)}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {method.responses && (
              <div>
                <h5 className="text-sm mb-3" style={{ color: 'var(--stash-text-bright)' }}>Responses</h5>
                <div className="space-y-2">
                  {Object.entries(method.responses).map(([statusCode, response]: [string, any]) => {
                    const isSuccess = statusCode.startsWith('2');
                    const isError = statusCode.startsWith('4') || statusCode.startsWith('5');
                    
                    return (
                      <div 
                        key={statusCode}
                        className="p-3 rounded"
                        style={{ backgroundColor: 'var(--stash-bg-base)' }}
                      >
                        <div className="flex items-center gap-2 mb-2">
                          <span 
                            className="px-2 py-0.5 rounded text-sm font-mono"
                            style={{ 
                              backgroundColor: isSuccess 
                                ? 'rgba(166, 227, 161, 0.2)' 
                                : isError 
                                ? 'rgba(243, 139, 168, 0.2)' 
                                : 'rgba(137, 180, 250, 0.2)',
                              color: isSuccess 
                                ? '#a6e3a1' 
                                : isError 
                                ? '#f38ba8' 
                                : '#89b4fa'
                            }}
                          >
                            {statusCode}
                          </span>
                          <span className="text-sm" style={{ color: 'var(--stash-text-primary)' }}>
                            {response.description}
                          </span>
                        </div>
                        {response.content && Object.entries(response.content).map(([contentType, content]: [string, any]) => (
                          <div key={contentType} className="mt-2">
                            <div className="text-xs mb-2" style={{ color: 'var(--stash-text-muted)' }}>
                              Content-Type: {contentType}
                            </div>
                            {content.schema && renderSchema(content.schema)}
                            {content.example && (
                              <pre 
                                className="mt-2 p-2 rounded text-xs overflow-x-auto"
                                style={{ 
                                  backgroundColor: 'var(--stash-bg-code)',
                                  color: 'var(--stash-text-secondary)'
                                }}
                              >
                                {JSON.stringify(content.example, null, 2)}
                              </pre>
                            )}
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  if (error) {
    return (
      <div className="h-full w-full flex items-center justify-center p-8" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <div className="text-center">
          <p style={{ color: '#f38ba8' }} className="mb-2">
            {error}
          </p>
          <p style={{ color: 'var(--stash-text-secondary)' }} className="text-sm">
            Please check that the file contains valid OpenAPI 3.0 or Swagger 2.0 JSON
          </p>
        </div>
      </div>
    );
  }

  if (!apiSpec) {
    return (
      <div className="h-full w-full flex items-center justify-center" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <p style={{ color: 'var(--stash-text-secondary)' }}>Loading API documentation...</p>
      </div>
    );
  }

  const allTags = getAllTags();
  const filteredMethods = getFilteredMethods();

  return (
    <div className="h-full w-full overflow-auto" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
      <div className="max-w-[1400px] mx-auto px-8 py-8">
        {/* Header */}
        <div className="mb-8 pb-6" style={{ borderBottom: '1px solid var(--stash-border)' }}>
          <div className="flex items-start justify-between mb-4">
            <div className="flex items-center gap-4">
              <div 
                className="p-3 rounded-lg"
                style={{ backgroundColor: 'var(--stash-bg-surface)' }}
              >
                <Globe className="w-8 h-8" style={{ color: 'var(--stash-accent)' }} />
              </div>
              <div>
                {apiSpec.info?.title && (
                  <h1 className="text-3xl mb-2" style={{ color: 'var(--stash-text-bright)' }}>
                    {apiSpec.info.title}
                  </h1>
                )}
                <div className="flex items-center gap-2">
                  {apiSpec.info?.version && (
                    <span 
                      className="px-3 py-1 rounded text-sm font-mono"
                      style={{ 
                        backgroundColor: 'rgba(148, 226, 213, 0.2)',
                        color: 'var(--stash-accent)'
                      }}
                    >
                      v{apiSpec.info.version}
                    </span>
                  )}
                  {(apiSpec.openapi || apiSpec.swagger) && (
                    <span 
                      className="px-3 py-1 rounded text-sm"
                      style={{ 
                        backgroundColor: 'var(--stash-bg-surface)',
                        color: 'var(--stash-text-muted)'
                      }}
                    >
                      OpenAPI {apiSpec.openapi || apiSpec.swagger}
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>
          
          {apiSpec.info?.description && (
            <p className="text-base mb-4" style={{ color: 'var(--stash-text-secondary)' }}>
              {apiSpec.info.description}
            </p>
          )}

          {apiSpec.info?.contact && (
            <div className="flex items-center gap-4 text-sm" style={{ color: 'var(--stash-text-muted)' }}>
              {apiSpec.info.contact.name && (
                <span>Contact: {apiSpec.info.contact.name}</span>
              )}
              {apiSpec.info.contact.email && (
                <span>Email: {apiSpec.info.contact.email}</span>
              )}
            </div>
          )}
        </div>

        {/* Servers */}
        {apiSpec.servers && apiSpec.servers.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-3">
              <Server className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
              <h3 className="text-lg" style={{ color: 'var(--stash-text-bright)' }}>Servers</h3>
            </div>
            <div className="space-y-2">
              {apiSpec.servers.map((server: any, idx: number) => (
                <div 
                  key={idx}
                  className="p-3 rounded-lg flex items-center justify-between"
                  style={{ 
                    backgroundColor: 'var(--stash-bg-surface)',
                    border: '1px solid var(--stash-border)'
                  }}
                >
                  <div>
                    <code 
                      className="text-sm font-mono"
                      style={{ color: 'var(--stash-accent)' }}
                    >
                      {server.url}
                    </code>
                    {server.description && (
                      <p className="text-xs mt-1" style={{ color: 'var(--stash-text-muted)' }}>
                        {server.description}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() => copyToClipboard(server.url, `server-${idx}`)}
                    className="p-1 rounded"
                    style={{ color: 'var(--stash-text-muted)' }}
                    title="Copy URL"
                  >
                    {copiedItem === `server-${idx}` ? (
                      <Check className="w-4 h-4" style={{ color: 'var(--stash-accent)' }} />
                    ) : (
                      <Copy className="w-4 h-4" />
                    )}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Tag Filter */}
        {allTags.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center gap-2 flex-wrap">
              <button
                onClick={() => setSelectedTag('all')}
                className="px-3 py-1.5 rounded text-sm transition-all duration-150"
                style={{
                  backgroundColor: selectedTag === 'all' ? 'var(--stash-accent)' : 'var(--stash-bg-surface)',
                  color: selectedTag === 'all' ? 'var(--stash-bg-base)' : 'var(--stash-text-secondary)',
                  border: '1px solid var(--stash-border)'
                }}
              >
                All Endpoints
              </button>
              {allTags.map(tag => (
                <button
                  key={tag}
                  onClick={() => setSelectedTag(tag)}
                  className="px-3 py-1.5 rounded text-sm transition-all duration-150 flex items-center gap-2"
                  style={{
                    backgroundColor: selectedTag === tag ? 'var(--stash-accent)' : 'var(--stash-bg-surface)',
                    color: selectedTag === tag ? 'var(--stash-bg-base)' : 'var(--stash-text-secondary)',
                    border: '1px solid var(--stash-border)'
                  }}
                >
                  <Tag className="w-3 h-3" />
                  {tag}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Endpoints */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-4">
            <Code className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
            <h3 className="text-lg" style={{ color: 'var(--stash-text-bright)' }}>
              Endpoints
              <span className="text-sm ml-2" style={{ color: 'var(--stash-text-muted)' }}>
                ({filteredMethods.length})
              </span>
            </h3>
          </div>
          <div className="space-y-2">
            {filteredMethods.map(method => 
              renderEndpoint(method)
            )}
          </div>
        </div>

        {/* Schemas */}
        {apiSpec.components?.schemas && (
          <div>
            <div className="flex items-center gap-2 mb-4">
              <FileJson className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
              <h3 className="text-lg" style={{ color: 'var(--stash-text-bright)' }}>Schemas</h3>
            </div>
            <div className="space-y-3">
              {Object.entries(apiSpec.components.schemas).map(([schemaName, schema]: [string, any]) => (
                <div
                  key={schemaName}
                  className="p-4 rounded-lg"
                  style={{ 
                    backgroundColor: 'var(--stash-bg-surface)',
                    border: '1px solid var(--stash-border)'
                  }}
                >
                  <h4 className="text-base mb-3" style={{ color: 'var(--stash-text-bright)' }}>
                    {schemaName}
                  </h4>
                  {schema.description && (
                    <p className="text-sm mb-3" style={{ color: 'var(--stash-text-secondary)' }}>
                      {schema.description}
                    </p>
                  )}
                  {renderSchema(schema, schemaName)}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}