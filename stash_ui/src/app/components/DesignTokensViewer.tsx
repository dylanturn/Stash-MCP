import React, { useState, useEffect } from 'react';
import { ChevronDown, ChevronRight, Copy, Check, Palette, Type, Ruler, Search, X } from 'lucide-react';

interface DesignTokensViewerProps {
  content: string;
  onSectionsChange?: (sections: Array<{ id: string; title: string; color?: string }>) => void;
  onActiveSectionChange?: (id: string | null) => void;
}

interface TokenData {
  [key: string]: any;
}

export function DesignTokensViewer({ content, onSectionsChange, onActiveSectionChange }: DesignTokensViewerProps) {
  const [error, setError] = useState<string | null>(null);
  const [tokens, setTokens] = useState<TokenData | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['colors', 'spacing', 'typography']));
  const [copiedPath, setCopiedPath] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<string>('all');

  useEffect(() => {
    try {
      const parsed = JSON.parse(content);
      setTokens(parsed);
      setError(null);
    } catch (e) {
      console.error('Failed to parse design tokens:', e);
      setError('Invalid JSON format');
    }
  }, [content]);

  // Notify parent of available sections when tokens change
  useEffect(() => {
    if (!tokens || !onSectionsChange) return;

    const sections: Array<{ id: string; title: string; color?: string }> = [];
    
    // Extract top-level token categories
    Object.keys(tokens).forEach((key) => {
      const categoryName = key.charAt(0).toUpperCase() + key.slice(1);
      sections.push({
        id: key,
        title: categoryName,
        color: getCategoryColor(key)
      });
    });

    onSectionsChange(sections);
  }, [tokens, onSectionsChange]);

  // Helper to assign colors to different token categories
  const getCategoryColor = (category: string): string => {
    const colorMap: { [key: string]: string } = {
      colors: '#f9e2af',
      color: '#f9e2af',
      spacing: '#89b4fa',
      space: '#89b4fa',
      typography: '#a6e3a1',
      type: '#a6e3a1',
      font: '#a6e3a1',
      size: '#fab387',
      sizing: '#fab387',
      border: '#f38ba8',
      shadow: '#cba6f7',
      radius: '#94e2d5'
    };
    
    return colorMap[category.toLowerCase()] || 'var(--stash-accent)';
  };

  const toggleSection = (path: string) => {
    const newExpanded = new Set(expandedSections);
    if (newExpanded.has(path)) {
      newExpanded.delete(path);
    } else {
      newExpanded.add(path);
    }
    setExpandedSections(newExpanded);
  };

  const copyToClipboard = (text: string, path: string) => {
    // Fallback method for clipboard API
    try {
      // Try modern Clipboard API first
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          setCopiedPath(path);
          setTimeout(() => setCopiedPath(null), 2000);
        }).catch(() => {
          // Fallback if clipboard API fails
          fallbackCopy(text, path);
        });
      } else {
        // Use fallback if Clipboard API not available
        fallbackCopy(text, path);
      }
    } catch (err) {
      fallbackCopy(text, path);
    }
  };

  const fallbackCopy = (text: string, path: string) => {
    // Create a temporary textarea
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    
    try {
      document.execCommand('copy');
      setCopiedPath(path);
      setTimeout(() => setCopiedPath(null), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    } finally {
      document.body.removeChild(textarea);
    }
  };

  const expandAll = () => {
    if (!tokens) return;
    const allPaths = new Set<string>();
    const collectPaths = (obj: any, path: string = '') => {
      Object.entries(obj).forEach(([key, value]) => {
        if (key.startsWith('$')) return;
        const currentPath = path ? `${path}.${key}` : key;
        if (typeof value === 'object' && value !== null && !('$value' in value)) {
          allPaths.add(currentPath);
          collectPaths(value, currentPath);
        }
      });
    };
    collectPaths(tokens);
    setExpandedSections(allPaths);
  };

  const collapseAll = () => {
    setExpandedSections(new Set());
  };

  const renderColorSwatch = (color: string, size: 'sm' | 'md' | 'lg' = 'md') => {
    if (typeof color !== 'string') return null;
    
    // Support various color formats
    const isColor = color.startsWith('#') || 
                    color.startsWith('rgb') || 
                    color.startsWith('hsl') ||
                    color.startsWith('var(');
    
    if (!isColor) return null;

    const sizeClasses = {
      sm: 'w-6 h-6',
      md: 'w-10 h-10',
      lg: 'w-16 h-16'
    };
    
    return (
      <div 
        className={`inline-block ${sizeClasses[size]} rounded border shadow-sm`}
        style={{ 
          backgroundColor: color,
          borderColor: 'var(--stash-border)'
        }}
        title={color}
      />
    );
  };

  const renderColorPalette = (colors: any, parentPath: string) => {
    const colorEntries = Object.entries(colors).filter(([key]) => !key.startsWith('$'));
    
    return (
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
        {colorEntries.map(([key, value]: [string, any]) => {
          const currentPath = `${parentPath}.${key}`;
          
          if (typeof value === 'object' && '$value' in value) {
            const colorValue = value.$value;
            return (
              <div
                key={currentPath}
                className="p-4 rounded-lg transition-all duration-150 cursor-pointer group"
                style={{ 
                  backgroundColor: 'var(--stash-bg-surface)',
                  border: '1px solid var(--stash-border)'
                }}
                onClick={() => copyToClipboard(colorValue, currentPath)}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--stash-accent)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--stash-border)';
                }}
              >
                <div className="flex flex-col gap-3">
                  {renderColorSwatch(colorValue, 'lg')}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium" style={{ color: 'var(--stash-text-bright)' }}>
                        {key}
                      </span>
                      {copiedPath === currentPath ? (
                        <Check className="w-4 h-4" style={{ color: 'var(--stash-accent)' }} />
                      ) : (
                        <Copy className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--stash-text-muted)' }} />
                      )}
                    </div>
                    <code 
                      className="text-xs font-mono block"
                      style={{ color: 'var(--stash-accent)' }}
                    >
                      {colorValue}
                    </code>
                    {value.$description && (
                      <p className="text-xs mt-2" style={{ color: 'var(--stash-text-secondary)' }}>
                        {value.$description}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            );
          }
          
          return null;
        })}
      </div>
    );
  };

  const renderSpacingScale = (spacing: any, parentPath: string) => {
    const spacingEntries = Object.entries(spacing).filter(([key]) => !key.startsWith('$'));
    
    return (
      <div className="space-y-3">
        {spacingEntries.map(([key, value]: [string, any]) => {
          const currentPath = `${parentPath}.${key}`;
          
          if (typeof value === 'object' && '$value' in value) {
            const spacingValue = value.$value;
            // Parse spacing value to pixels for visualization
            const pxValue = spacingValue.includes('rem') 
              ? parseFloat(spacingValue) * 16 
              : parseFloat(spacingValue);
            
            return (
              <div
                key={currentPath}
                className="p-4 rounded-lg transition-all duration-150 cursor-pointer group"
                style={{ 
                  backgroundColor: 'var(--stash-bg-surface)',
                  border: '1px solid var(--stash-border)'
                }}
                onClick={() => copyToClipboard(spacingValue, currentPath)}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--stash-accent)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--stash-border)';
                }}
              >
                <div className="flex items-center gap-4">
                  {/* Visual representation */}
                  <div 
                    className="rounded"
                    style={{ 
                      width: `${Math.min(pxValue, 200)}px`,
                      height: '24px',
                      backgroundColor: 'var(--stash-accent)',
                      opacity: 0.3
                    }}
                  />
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium" style={{ color: 'var(--stash-text-bright)' }}>
                        {key}
                      </span>
                      {copiedPath === currentPath ? (
                        <Check className="w-4 h-4" style={{ color: 'var(--stash-accent)' }} />
                      ) : (
                        <Copy className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--stash-text-muted)' }} />
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <code className="text-sm font-mono" style={{ color: 'var(--stash-accent)' }}>
                        {spacingValue}
                      </code>
                      <span className="text-xs" style={{ color: 'var(--stash-text-muted)' }}>
                        ({pxValue}px)
                      </span>
                    </div>
                    {value.$description && (
                      <p className="text-xs mt-1" style={{ color: 'var(--stash-text-secondary)' }}>
                        {value.$description}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            );
          }
          
          return null;
        })}
      </div>
    );
  };

  const renderTypographyPreview = (typography: any, parentPath: string, type: string) => {
    const entries = Object.entries(typography).filter(([key]) => !key.startsWith('$'));
    
    if (type === 'font-size') {
      return (
        <div className="space-y-3">
          {entries.map(([key, value]: [string, any]) => {
            const currentPath = `${parentPath}.${key}`;
            
            if (typeof value === 'object' && '$value' in value) {
              const sizeValue = value.$value;
              
              return (
                <div
                  key={currentPath}
                  className="p-4 rounded-lg transition-all duration-150 cursor-pointer group"
                  style={{ 
                    backgroundColor: 'var(--stash-bg-surface)',
                    border: '1px solid var(--stash-border)'
                  }}
                  onClick={() => copyToClipboard(sizeValue, currentPath)}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = 'var(--stash-accent)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'var(--stash-border)';
                  }}
                >
                  <div className="flex items-baseline justify-between gap-4">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2">
                        <span className="text-sm font-medium" style={{ color: 'var(--stash-text-bright)' }}>
                          {key}
                        </span>
                        <code className="text-xs font-mono" style={{ color: 'var(--stash-accent)' }}>
                          {sizeValue}
                        </code>
                        {copiedPath === currentPath ? (
                          <Check className="w-4 h-4 ml-auto" style={{ color: 'var(--stash-accent)' }} />
                        ) : (
                          <Copy className="w-4 h-4 ml-auto opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--stash-text-muted)' }} />
                        )}
                      </div>
                      <div style={{ fontSize: sizeValue, color: 'var(--stash-text-primary)', lineHeight: '1.2' }}>
                        The quick brown fox jumps over the lazy dog
                      </div>
                      {value.$description && (
                        <p className="text-xs mt-2" style={{ color: 'var(--stash-text-secondary)' }}>
                          {value.$description}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              );
            }
            
            return null;
          })}
        </div>
      );
    }

    if (type === 'font-weight') {
      return (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {entries.map(([key, value]: [string, any]) => {
            const currentPath = `${parentPath}.${key}`;
            
            if (typeof value === 'object' && '$value' in value) {
              const weightValue = value.$value;
              
              return (
                <div
                  key={currentPath}
                  className="p-4 rounded-lg transition-all duration-150 cursor-pointer group"
                  style={{ 
                    backgroundColor: 'var(--stash-bg-surface)',
                    border: '1px solid var(--stash-border)'
                  }}
                  onClick={() => copyToClipboard(weightValue, currentPath)}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = 'var(--stash-accent)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'var(--stash-border)';
                  }}
                >
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium" style={{ color: 'var(--stash-text-bright)' }}>
                        {key}
                      </span>
                      {copiedPath === currentPath ? (
                        <Check className="w-4 h-4" style={{ color: 'var(--stash-accent)' }} />
                      ) : (
                        <Copy className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--stash-text-muted)' }} />
                      )}
                    </div>
                    <code className="text-xs font-mono" style={{ color: 'var(--stash-accent)' }}>
                      {weightValue}
                    </code>
                    <div style={{ fontWeight: weightValue, color: 'var(--stash-text-primary)' }}>
                      Sample Text
                    </div>
                  </div>
                </div>
              );
            }
            
            return null;
          })}
        </div>
      );
    }

    if (type === 'font-family') {
      return (
        <div className="space-y-3">
          {entries.map(([key, value]: [string, any]) => {
            const currentPath = `${parentPath}.${key}`;
            
            if (typeof value === 'object' && '$value' in value) {
              const familyValue = Array.isArray(value.$value) ? value.$value.join(', ') : value.$value;
              
              return (
                <div
                  key={currentPath}
                  className="p-4 rounded-lg transition-all duration-150 cursor-pointer group"
                  style={{ 
                    backgroundColor: 'var(--stash-bg-surface)',
                    border: '1px solid var(--stash-border)'
                  }}
                  onClick={() => copyToClipboard(familyValue, currentPath)}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = 'var(--stash-accent)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'var(--stash-border)';
                  }}
                >
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium" style={{ color: 'var(--stash-text-bright)' }}>
                        {key}
                      </span>
                      {copiedPath === currentPath ? (
                        <Check className="w-4 h-4" style={{ color: 'var(--stash-accent)' }} />
                      ) : (
                        <Copy className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-opacity" style={{ color: 'var(--stash-text-muted)' }} />
                      )}
                    </div>
                    <code className="text-xs font-mono" style={{ color: 'var(--stash-accent)' }}>
                      {familyValue}
                    </code>
                    <div 
                      className="text-lg"
                      style={{ fontFamily: familyValue, color: 'var(--stash-text-primary)' }}
                    >
                      The quick brown fox jumps over the lazy dog
                    </div>
                    {value.$description && (
                      <p className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
                        {value.$description}
                      </p>
                    )}
                  </div>
                </div>
              );
            }
            
            return null;
          })}
        </div>
      );
    }

    // Default rendering for other typography tokens
    return null;
  };

  const renderTokenValue = (value: any, type?: string, path?: string) => {
    if (typeof value === 'object' && value !== null) {
      if (value.$value !== undefined) {
        const actualValue = value.$value;
        const description = value.$description;
        const tokenType = value.$type || type;
        
        return (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              {tokenType === 'color' && renderColorSwatch(actualValue, 'sm')}
              <code 
                className="px-2 py-1 rounded text-sm font-mono"
                style={{ 
                  backgroundColor: 'var(--stash-bg-code)',
                  color: 'var(--stash-accent)'
                }}
              >
                {typeof actualValue === 'object' ? JSON.stringify(actualValue) : String(actualValue)}
              </code>
              {path && (
                <button
                  onClick={() => copyToClipboard(typeof actualValue === 'object' ? JSON.stringify(actualValue) : String(actualValue), path)}
                  className="p-1 rounded hover:bg-opacity-20"
                  style={{ 
                    color: 'var(--stash-text-muted)',
                    backgroundColor: copiedPath === path ? 'rgba(148, 226, 213, 0.2)' : 'transparent'
                  }}
                  title="Copy value"
                >
                  {copiedPath === path ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                </button>
              )}
            </div>
            {description && (
              <p className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
                {description}
              </p>
            )}
            {tokenType && (
              <span 
                className="inline-block px-2 py-0.5 rounded text-xs"
                style={{ 
                  backgroundColor: 'rgba(137, 180, 250, 0.2)',
                  color: '#89b4fa'
                }}
              >
                {tokenType}
              </span>
            )}
          </div>
        );
      }
      
      return (
        <code 
          className="px-2 py-1 rounded text-sm font-mono block"
          style={{ 
            backgroundColor: 'var(--stash-bg-code)',
            color: 'var(--stash-text-secondary)'
          }}
        >
          {JSON.stringify(value, null, 2)}
        </code>
      );
    }
    
    return (
      <code 
        className="px-2 py-1 rounded text-sm font-mono"
        style={{ 
          backgroundColor: 'var(--stash-bg-code)',
          color: 'var(--stash-accent)' 
        }}
      >
        {String(value)}
      </code>
    );
  };

  const renderTokenGroup = (data: any, path: string = '', level: number = 0): React.ReactNode => {
    if (!data || typeof data !== 'object') return null;

    const entries = Object.entries(data).filter(([key]) => !key.startsWith('$'));
    
    return entries.map(([key, value]) => {
      const currentPath = path ? `${path}.${key}` : key;
      const isExpanded = expandedSections.has(currentPath);
      
      // Check if this is a token value (has $value) or a group
      const isTokenValue = typeof value === 'object' && value !== null && '$value' in value;
      const hasChildren = typeof value === 'object' && value !== null && !isTokenValue;
      const tokenType = data.$type;

      // Check if this is a special visualizable group
      const isColorGroup = (currentPath === 'colors' || currentPath.includes('colors.')) && hasChildren;
      const isSpacingGroup = currentPath === 'spacing' && hasChildren;
      const isTypographySubgroup = currentPath.includes('typography.font-size') || 
                                   currentPath.includes('typography.font-weight') ||
                                   currentPath.includes('typography.font-family');
      
      if (isTokenValue) {
        return (
          <div 
            key={currentPath} 
            className="py-3 px-4 rounded mb-2"
            style={{ 
              backgroundColor: 'var(--stash-bg-surface)',
              borderLeft: '3px solid var(--stash-accent)'
            }}
          >
            <div className="flex justify-between items-start mb-2">
              <h4 
                className="font-medium"
                style={{ color: 'var(--stash-text-bright)' }}
              >
                {key}
              </h4>
              <span 
                className="text-xs px-2 py-0.5 rounded font-mono"
                style={{ 
                  backgroundColor: 'var(--stash-bg-base)',
                  color: 'var(--stash-text-muted)'
                }}
              >
                {currentPath}
              </span>
            </div>
            {renderTokenValue(value, tokenType, currentPath)}
          </div>
        );
      }
      
      if (hasChildren) {
        return (
          <div key={currentPath} className="mb-4">
            <button
              onClick={() => toggleSection(currentPath)}
              className="flex items-center gap-2 w-full p-3 rounded mb-3 transition-colors"
              style={{ 
                backgroundColor: 'var(--stash-bg-surface)',
                color: 'var(--stash-text-bright)',
                border: '1px solid var(--stash-border)'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--stash-accent)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--stash-border)';
              }}
            >
              {isExpanded ? (
                <ChevronDown className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
              ) : (
                <ChevronRight className="w-5 h-5" style={{ color: 'var(--stash-text-muted)' }} />
              )}
              <span className="font-semibold text-base">{key}</span>
              <span className="text-xs ml-auto" style={{ color: 'var(--stash-text-muted)' }}>
                {Object.keys(value).filter(k => !k.startsWith('$')).length} items
              </span>
            </button>
            {isExpanded && (
              <div className="ml-2 space-y-2">
                {isColorGroup ? (
                  renderColorPalette(value, currentPath)
                ) : isSpacingGroup ? (
                  renderSpacingScale(value, currentPath)
                ) : isTypographySubgroup ? (
                  renderTypographyPreview(value, currentPath, key)
                ) : (
                  renderTokenGroup(value, currentPath, level + 1)
                )}
              </div>
            )}
          </div>
        );
      }
      
      return null;
    });
  };

  if (error) {
    return (
      <div className="h-full w-full flex items-center justify-center p-8" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <div className="text-center">
          <p style={{ color: '#f38ba8' }} className="mb-2">
            {error}
          </p>
          <p style={{ color: 'var(--stash-text-secondary)' }} className="text-sm">
            Please check that the file contains valid Design Tokens JSON
          </p>
        </div>
      </div>
    );
  }

  if (!tokens) {
    return (
      <div className="h-full w-full flex items-center justify-center" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <p style={{ color: 'var(--stash-text-secondary)' }}>Loading design tokens...</p>
      </div>
    );
  }

  const meta = tokens.meta;

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
                <Palette className="w-8 h-8" style={{ color: 'var(--stash-accent)' }} />
              </div>
              <div>
                {meta?.name && (
                  <h1 className="text-3xl mb-2" style={{ color: 'var(--stash-text-bright)' }}>
                    {meta.name}
                  </h1>
                )}
                <div className="flex items-center gap-2">
                  {meta?.version && (
                    <span 
                      className="px-3 py-1 rounded text-sm font-mono"
                      style={{ 
                        backgroundColor: 'rgba(148, 226, 213, 0.2)',
                        color: 'var(--stash-accent)'
                      }}
                    >
                      v{meta.version}
                    </span>
                  )}
                </div>
              </div>
            </div>
            
            {/* Controls */}
            <div className="flex items-center gap-2">
              <button
                onClick={expandAll}
                className="px-3 py-2 rounded text-sm transition-all duration-150"
                style={{ 
                  backgroundColor: 'var(--stash-bg-surface)',
                  color: 'var(--stash-text-secondary)',
                  border: '1px solid var(--stash-border)'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--stash-bg-surface)';
                }}
              >
                Expand All
              </button>
              <button
                onClick={collapseAll}
                className="px-3 py-2 rounded text-sm transition-all duration-150"
                style={{ 
                  backgroundColor: 'var(--stash-bg-surface)',
                  color: 'var(--stash-text-secondary)',
                  border: '1px solid var(--stash-border)'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--stash-bg-surface)';
                }}
              >
                Collapse All
              </button>
            </div>
          </div>
          
          {meta?.description && (
            <p className="text-base" style={{ color: 'var(--stash-text-secondary)' }}>
              {meta.description}
            </p>
          )}
        </div>

        {/* Token Groups */}
        <div className="space-y-6">
          {renderTokenGroup(tokens)}
        </div>
      </div>
    </div>
  );
}