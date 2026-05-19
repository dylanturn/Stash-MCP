import React, { useState, useEffect, useRef, useCallback } from 'react';
import { FileNode } from '../types';
import { Eye, Edit, Save, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { Heading } from './TableOfContents';
import { Endpoint } from './EndpointsList';
import { Section } from './SectionsList';
import { MermaidDiagram } from './MermaidDiagram';
import { OpenApiViewer } from './OpenApiViewer';
import { AsyncApiViewer } from './AsyncApiViewer';
import { DesignTokensViewer } from './DesignTokensViewer';
import { ComponentContractViewer } from './ComponentContractViewer';
import { ArazzoViewer } from './ArazzoViewer';
import { BinaryFileViewer, classifyBinary } from './BinaryFileViewer';

interface DocumentViewerProps {
  file: FileNode | null;
  onSave: (content: string) => void;
  onNavigate?: (path: string) => void;
  onHeadingsChange?: (headings: Heading[]) => void;
  onActiveHeadingChange?: (id: string | null) => void;
  onEndpointsChange?: (endpoints: Endpoint[]) => void;
  onActiveEndpointChange?: (id: string | null) => void;
  onSectionsChange?: (sections: Section[]) => void;
  onActiveSectionChange?: (id: string | null) => void;
  onSectionsTitleChange?: (title: string) => void;
  /** Returns a URL the browser can fetch the raw bytes of a content
   * file from. Used to render images and PDFs that can't go through
   * the JSON content endpoint. */
  rawUrl?: (path: string) => string;
}

/** Check whether an href points to an external URL. */
function isExternalLink(href: string): boolean {
  return /^https?:\/\//.test(href) || href.startsWith('mailto:');
}

/** Resolve a potentially-relative href against the current file's directory. */
function resolveInternalPath(href: string, currentFilePath: string): string {
  // Strip leading hash — anchor-only links
  if (href.startsWith('#')) return '';

  // Absolute paths within the content store (leading /)
  if (href.startsWith('/')) return href.replace(/^\/+/, '');

  // Relative path — resolve against the directory of the current file
  const dir = currentFilePath.includes('/')
    ? currentFilePath.substring(0, currentFilePath.lastIndexOf('/'))
    : '';
  const parts = (dir ? `${dir}/${href}` : href).split('/');
  const resolved: string[] = [];
  for (const part of parts) {
    if (part === '.' || part === '') continue;
    if (part === '..') {
      resolved.pop();
    } else {
      resolved.push(part);
    }
  }
  return resolved.join('/');
}

export function DocumentViewer({
  file,
  onSave,
  onNavigate,
  onHeadingsChange,
  onActiveHeadingChange,
  onEndpointsChange,
  onActiveEndpointChange,
  onSectionsChange,
  onActiveSectionChange,
  onSectionsTitleChange,
  rawUrl,
}: DocumentViewerProps) {
  const [mode, setMode] = useState<'view' | 'edit'>('view');
  const [editContent, setEditContent] = useState('');
  const [hasChanges, setHasChanges] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);

  // Memoize the async API sections callback to prevent infinite loops
  const handleAsyncApiSectionsChange = useCallback((sections: Section[]) => {
    onSectionsChange?.(sections);
    onSectionsTitleChange?.('AsyncAPI Sections');
  }, [onSectionsChange, onSectionsTitleChange]);

  // Memoize the Arazzo sections callback to prevent infinite loops
  const handleArazzoSectionsChange = useCallback((sections: Section[]) => {
    onSectionsChange?.(sections);
    onSectionsTitleChange?.('Arazzo Sections');
  }, [onSectionsChange, onSectionsTitleChange]);

  // Memoize the Design Tokens sections callback to prevent infinite loops
  const handleDesignTokensSectionsChange = useCallback((sections: Section[]) => {
    onSectionsChange?.(sections);
    onSectionsTitleChange?.('Design Tokens');
  }, [onSectionsChange, onSectionsTitleChange]);

  // Memoize the Component Contract sections callback to prevent infinite loops
  const handleComponentContractSectionsChange = useCallback((sections: Section[]) => {
    onSectionsChange?.(sections);
    onSectionsTitleChange?.('Component Sections');
  }, [onSectionsChange, onSectionsTitleChange]);

  // Clear sections when file changes to prevent old sections from persisting
  useEffect(() => {
    // Clear sections immediately when file changes
    onSectionsChange?.([]);
    onSectionsTitleChange?.('');
    onEndpointsChange?.([]);
    onHeadingsChange?.([]);
  }, [file.id, onSectionsChange, onSectionsTitleChange, onEndpointsChange, onHeadingsChange]);

  // Extract headings from markdown content
  const extractHeadings = (content: string): Heading[] => {
    const headingRegex = /^(#{1,3})\s+(.+)$/gm;
    const headings: Heading[] = [];
    let match;

    while ((match = headingRegex.exec(content)) !== null) {
      const level = match[1].length;
      const text = match[2].trim();
      const id = `heading-${text.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
      headings.push({ id, text, level });
    }

    return headings;
  };

  // Helper to extract text from React children for ID generation
  const getTextFromChildren = (children: React.ReactNode): string => {
    if (typeof children === 'string') return children;
    if (typeof children === 'number') return String(children);
    if (Array.isArray(children)) return children.map(getTextFromChildren).join('');
    if (children && typeof children === 'object' && 'props' in children) {
      return getTextFromChildren((children as any).props.children);
    }
    return '';
  };

  useEffect(() => {
    if (file) {
      setEditContent(file.content || '');
      setMode('view');
      setHasChanges(false);

      // Extract and report headings for markdown files
      if (file.extension === 'md' && file.content) {
        const headings = extractHeadings(file.content);
        onHeadingsChange?.(headings);
      } else {
        onHeadingsChange?.([]);
      }
    }
  }, [file, onHeadingsChange]);

  // Track active heading via scroll position
  useEffect(() => {
    if (mode !== 'view' || !file || file.extension !== 'md') return;

    const scrollEl = contentRef.current;
    if (!scrollEl) return;

    // Offset from the top of the scroll container where a heading is
    // considered "active" (matches the scrollMarginTop on headings).
    const OFFSET = 100;

    let ticking = false;

    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        ticking = false;
        const headings = scrollEl.querySelectorAll('h1, h2, h3');
        let activeId: string | null = null;

        for (const heading of headings) {
          const rect = heading.getBoundingClientRect();
          const containerRect = scrollEl.getBoundingClientRect();
          if (rect.top - containerRect.top <= OFFSET) {
            activeId = heading.id;
          } else {
            break;
          }
        }

        onActiveHeadingChange?.(activeId);
      });
    };

    // Run once on mount so the initial heading is highlighted
    const timeoutId = setTimeout(onScroll, 150);
    scrollEl.addEventListener('scroll', onScroll, { passive: true });

    return () => {
      clearTimeout(timeoutId);
      scrollEl.removeEventListener('scroll', onScroll);
    };
  }, [mode, file, onActiveHeadingChange]);

  const handleSave = () => {
    onSave(editContent);
    setHasChanges(false);
    setMode('view');
  };

  const handleDiscard = () => {
    setEditContent(file?.content || '');
    setHasChanges(false);
    setMode('view');
  };

  const handleContentChange = (value: string) => {
    setEditContent(value);
    setHasChanges(value !== (file?.content || ''));
  };

  if (!file) {
    return (
      <div
        className="h-full flex items-center justify-center"
        style={{ backgroundColor: 'var(--stash-bg-base)' }}
      >
        <div className="text-center">
          <p style={{ color: 'var(--stash-text-secondary)' }}>
            Select a file to view its contents
          </p>
        </div>
      </div>
    );
  }

  const isMarkdown = file.extension === 'md';
  
  // Check if file is an OpenAPI spec
  const isOpenApiSpec = () => {
    if (!file.content || (file.extension !== 'json' && file.extension !== 'yaml' && file.extension !== 'yml')) {
      return false;
    }
    
    try {
      const content = JSON.parse(file.content);
      // Check for OpenAPI 3.x or Swagger 2.0 indicators
      return !!(content.openapi || content.swagger);
    } catch (e) {
      // If JSON parse fails, it might be YAML - we'll handle that in the ApiDocViewer
      return false;
    }
  };

  // Check if file is an AsyncAPI spec
  const isAsyncApiSpec = () => {
    if (!file.content || (file.extension !== 'json' && file.extension !== 'yaml' && file.extension !== 'yml')) {
      return false;
    }
    
    try {
      const content = JSON.parse(file.content);
      return !!content.asyncapi;
    } catch (e) {
      // Could be YAML - check filename
      return file.name.includes('asyncapi');
    }
  };

  // Check if file is a Design Tokens spec
  const isDesignTokensSpec = () => {
    if (!file.content || file.extension !== 'json') {
      return false;
    }
    
    try {
      const content = JSON.parse(file.content);
      // Check for design tokens schema or common patterns
      return !!(content.$schema && content.$schema.includes('design-tokens')) ||
             (content.meta && (content.colors || content.spacing || content.typography));
    } catch (e) {
      return false;
    }
  };

  // Check if file is a Component Contract spec
  const isComponentContractSpec = () => {
    if (!file.content || file.extension !== 'json') {
      return false;
    }
    
    try {
      const content = JSON.parse(file.content);
      // Check for component contract - has a "contract" object with name/version
      return !!(content.contract && content.contract.name && content.contract.version);
    } catch (e) {
      return false;
    }
  };

  // Check if file is an Arazzo spec
  const isArazzoSpec = () => {
    if (!file.content || (file.extension !== 'json' && file.extension !== 'yaml' && file.extension !== 'yml')) {
      return false;
    }
    
    // Check filename first
    if (file.name.includes('arazzo')) {
      return true;
    }
    
    // For JSON files, parse and check
    if (file.extension === 'json') {
      try {
        const content = JSON.parse(file.content);
        return !!content.arazzo;
      } catch (e) {
        return false;
      }
    }
    
    // For YAML files, check content starts with arazzo:
    if (file.extension === 'yaml' || file.extension === 'yml') {
      return file.content.trim().startsWith('arazzo:');
    }
    
    return false;
  };

  const isApiDoc = isOpenApiSpec();
  const isAsyncApi = isAsyncApiSpec();
  const isDesignTokens = isDesignTokensSpec();
  const isComponentContract = isComponentContractSpec();
  const isArazzo = isArazzoSpec();
  const binaryKind = classifyBinary(file.extension);
  const isMermaidFile =
    file.extension === 'mmd' || file.extension === 'mermaid';

  // Standalone Mermaid documents render as a diagram in view mode and
  // fall back to the text editor when the user switches to edit.
  if (isMermaidFile && mode === 'view') {
    return (
      <div className="h-full flex flex-col" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <div className="flex items-center border-b" style={{ borderColor: 'var(--stash-border)' }}>
          <button
            onClick={() => setMode('view')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: 'var(--stash-text-bright)',
              borderBottom: '2px solid var(--stash-accent)',
            }}
          >
            <Eye className="w-4 h-4" />
            <span className="text-sm">Diagram</span>
          </button>
          <button
            onClick={() => setMode('edit')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: 'var(--stash-text-secondary)',
              borderBottom: '2px solid transparent',
            }}
          >
            <Edit className="w-4 h-4" />
            <span className="text-sm">Edit</span>
            {hasChanges && (
              <div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: 'var(--stash-accent)' }}
              />
            )}
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-[900px] mx-auto px-8 py-8">
            <MermaidDiagram chart={file.content || ''} />
          </div>
        </div>
      </div>
    );
  }

  // Images and PDFs can't round-trip through the JSON content endpoint,
  // so view mode renders them directly from the raw bytes URL. HTML
  // and SVG artifacts are text — they render in a preview pane but
  // keep their source editable in a textarea.
  const isEditable = binaryKind === 'html' || binaryKind === 'svg';
  if (binaryKind !== null && (mode === 'view' || !isEditable)) {
    const previewLabel =
      binaryKind === 'image' ? 'Image'
        : binaryKind === 'pdf' ? 'PDF'
        : binaryKind === 'svg' ? 'SVG Preview'
        : 'HTML Preview';
    return (
      <div className="h-full flex flex-col" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <div className="flex items-center border-b" style={{ borderColor: 'var(--stash-border)' }}>
          <button
            onClick={() => setMode('view')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: 'var(--stash-text-bright)',
              borderBottom: '2px solid var(--stash-accent)',
            }}
          >
            <Eye className="w-4 h-4" />
            <span className="text-sm">{previewLabel}</span>
          </button>
          {isEditable && (
            <button
              onClick={() => setMode('edit')}
              className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
              style={{
                color: 'var(--stash-text-secondary)',
                borderBottom: '2px solid transparent',
              }}
            >
              <Edit className="w-4 h-4" />
              <span className="text-sm">Edit</span>
              {hasChanges && (
                <div
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: 'var(--stash-accent)' }}
                />
              )}
            </button>
          )}
        </div>
        <div className="flex-1 overflow-hidden">
          <BinaryFileViewer
            kind={binaryKind}
            rawUrl={rawUrl ? rawUrl(file.path) : undefined}
            htmlContent={file.content || ''}
            svgContent={file.content || ''}
            fileName={file.name}
          />
        </div>
      </div>
    );
  }

  // If it's an AsyncAPI spec, render with AsyncApiViewer
  if (isAsyncApi && mode === 'view') {
    return (
      <div className="h-full flex flex-col" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        {/* Tabs */}
        <div className="flex items-center border-b" style={{ borderColor: 'var(--stash-border)' }}>
          <button
            onClick={() => setMode('view')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: mode === 'view' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
              borderBottom: mode === 'view' ? '2px solid var(--stash-accent)' : '2px solid transparent'
            }}
          >
            <Eye className="w-4 h-4" />
            <span className="text-sm">AsyncAPI Docs</span>
          </button>
          <button
            onClick={() => setMode('edit')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: mode === 'edit' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
              borderBottom: mode === 'edit' ? '2px solid var(--stash-accent)' : '2px solid transparent'
            }}
          >
            <Edit className="w-4 h-4" />
            <span className="text-sm">Edit</span>
            {hasChanges && (
              <div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: 'var(--stash-accent)' }}
              />
            )}
          </button>
        </div>

        <div className="flex-1 overflow-hidden">
          <AsyncApiViewer 
            content={file.content || ''} 
            onSectionsChange={handleAsyncApiSectionsChange}
            onActiveSectionChange={onActiveSectionChange}
          />
        </div>
      </div>
    );
  }

  // If it's a Design Tokens spec, render with DesignTokensViewer
  if (isDesignTokens && mode === 'view') {
    return (
      <div className="h-full flex flex-col" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        {/* Tabs */}
        <div className="flex items-center border-b" style={{ borderColor: 'var(--stash-border)' }}>
          <button
            onClick={() => setMode('view')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: mode === 'view' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
              borderBottom: mode === 'view' ? '2px solid var(--stash-accent)' : '2px solid transparent'
            }}
          >
            <Eye className="w-4 h-4" />
            <span className="text-sm">Design Tokens</span>
          </button>
          <button
            onClick={() => setMode('edit')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: mode === 'edit' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
              borderBottom: mode === 'edit' ? '2px solid var(--stash-accent)' : '2px solid transparent'
            }}
          >
            <Edit className="w-4 h-4" />
            <span className="text-sm">Edit</span>
            {hasChanges && (
              <div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: 'var(--stash-accent)' }}
              />
            )}
          </button>
        </div>

        <div className="flex-1 overflow-hidden">
          <DesignTokensViewer content={file.content || ''} onSectionsChange={handleDesignTokensSectionsChange} />
        </div>
      </div>
    );
  }

  // If it's a Component Contract spec, render with ComponentContractViewer
  if (isComponentContract && mode === 'view') {
    return (
      <div className="h-full flex flex-col" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        {/* Tabs */}
        <div className="flex items-center border-b" style={{ borderColor: 'var(--stash-border)' }}>
          <button
            onClick={() => setMode('view')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: mode === 'view' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
              borderBottom: mode === 'view' ? '2px solid var(--stash-accent)' : '2px solid transparent'
            }}
          >
            <Eye className="w-4 h-4" />
            <span className="text-sm">Component Contract</span>
          </button>
          <button
            onClick={() => setMode('edit')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: mode === 'edit' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
              borderBottom: mode === 'edit' ? '2px solid var(--stash-accent)' : '2px solid transparent'
            }}
          >
            <Edit className="w-4 h-4" />
            <span className="text-sm">Edit</span>
            {hasChanges && (
              <div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: 'var(--stash-accent)' }}
              />
            )}
          </button>
        </div>

        <div className="flex-1 overflow-hidden">
          <ComponentContractViewer content={file.content || ''} onSectionsChange={handleComponentContractSectionsChange} />
        </div>
      </div>
    );
  }

  // If it's an Arazzo spec, render with ArazzoViewer
  if (isArazzo && mode === 'view') {
    return (
      <div className="h-full flex flex-col" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        {/* Tabs */}
        <div className="flex items-center border-b" style={{ borderColor: 'var(--stash-border)' }}>
          <button
            onClick={() => setMode('view')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: mode === 'view' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
              borderBottom: mode === 'view' ? '2px solid var(--stash-accent)' : '2px solid transparent'
            }}
          >
            <Eye className="w-4 h-4" />
            <span className="text-sm">Arazzo</span>
          </button>
          <button
            onClick={() => setMode('edit')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: mode === 'edit' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
              borderBottom: mode === 'edit' ? '2px solid var(--stash-accent)' : '2px solid transparent'
            }}
          >
            <Edit className="w-4 h-4" />
            <span className="text-sm">Edit</span>
            {hasChanges && (
              <div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: 'var(--stash-accent)' }}
              />
            )}
          </button>
        </div>

        <div className="flex-1 overflow-hidden">
          <ArazzoViewer content={file.content || ''} onSectionsChange={handleArazzoSectionsChange} />
        </div>
      </div>
    );
  }

  // If it's an API spec, render with ApiDocViewer
  if (isApiDoc && mode === 'view') {
    return (
      <div className="h-full flex flex-col" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        {/* Tabs */}
        <div className="flex items-center border-b" style={{ borderColor: 'var(--stash-border)' }}>
          <button
            onClick={() => setMode('view')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: mode === 'view' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
              borderBottom: mode === 'view' ? '2px solid var(--stash-accent)' : '2px solid transparent'
            }}
          >
            <Eye className="w-4 h-4" />
            <span className="text-sm">API Docs</span>
          </button>
          <button
            onClick={() => setMode('edit')}
            className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
            style={{
              color: mode === 'edit' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
              borderBottom: mode === 'edit' ? '2px solid var(--stash-accent)' : '2px solid transparent'
            }}
          >
            <Edit className="w-4 h-4" />
            <span className="text-sm">Edit</span>
            {hasChanges && (
              <div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: 'var(--stash-accent)' }}
              />
            )}
          </button>
        </div>

        <div className="flex-1 overflow-hidden">
          <OpenApiViewer 
            spec={file.content || ''} 
            onEndpointsChange={onEndpointsChange}
            onActiveEndpointChange={onActiveEndpointChange}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
      {/* Tabs */}
      <div className="flex items-center border-b" style={{ borderColor: 'var(--stash-border)' }}>
        <button
          onClick={() => setMode('view')}
          className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
          style={{
            color: mode === 'view' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
            borderBottom: mode === 'view' ? '2px solid var(--stash-accent)' : '2px solid transparent'
          }}
        >
          <Eye className="w-4 h-4" />
          <span className="text-sm">View</span>
          {hasChanges && mode === 'view' && (
            <div
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: 'var(--stash-accent)' }}
            />
          )}
        </button>
        <button
          onClick={() => setMode('edit')}
          className="flex items-center gap-2 px-6 py-3 transition-all duration-150 relative"
          style={{
            color: mode === 'edit' ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
            borderBottom: mode === 'edit' ? '2px solid var(--stash-accent)' : '2px solid transparent'
          }}
        >
          <Edit className="w-4 h-4" />
          <span className="text-sm">Edit</span>
          {hasChanges && mode === 'edit' && (
            <div
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: 'var(--stash-accent)' }}
            />
          )}
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto" ref={contentRef}>
        <div className="max-w-[900px] mx-auto px-8 py-8">
          {mode === 'view' ? (
            isMarkdown ? (
              <div
                className="prose prose-invert max-w-none"
                style={{
                  color: 'var(--stash-text-primary)',
                  fontSize: '18px',
                  lineHeight: '1.6'
                }}
              >
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  rehypePlugins={[rehypeRaw]}
                  components={{
                    h1: ({ children }) => {
                      const text = String(children);
                      const id = `heading-${text.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
                      return (
                        <h1 id={id} style={{ color: 'var(--stash-text-bright)', marginBottom: '1.5rem', scrollMarginTop: '80px' }}>
                          {children}
                        </h1>
                      );
                    },
                    h2: ({ children }) => {
                      const text = String(children);
                      const id = `heading-${text.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
                      return (
                        <h2 id={id} style={{ color: 'var(--stash-text-bright)', marginTop: '2rem', marginBottom: '1rem', scrollMarginTop: '80px' }}>
                          {children}
                        </h2>
                      );
                    },
                    h3: ({ children }) => {
                      const text = String(children);
                      const id = `heading-${text.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
                      return (
                        <h3 id={id} style={{ color: 'var(--stash-text-bright)', marginTop: '1.5rem', marginBottom: '0.75rem', scrollMarginTop: '80px' }}>
                          {children}
                        </h3>
                      );
                    },
                    p: ({ children }) => (
                      <p style={{ marginBottom: '1.5rem' }}>{children}</p>
                    ),
                    pre: ({ children, ...props }: any) => {
                      // react-markdown v9+ wraps fenced code in <pre><code>.
                      // We render the block-level version here and let
                      // the `code` component handle inline-only spans.
                      const codeChild = React.Children.toArray(children).find(
                        React.isValidElement
                      ) as React.ReactElement<any> | undefined;

                      if (codeChild) {
                        const className = codeChild.props?.className || '';
                        const match = /language-(\w+)/.exec(className);
                        const language = match ? match[1] : '';
                        const codeString = String(codeChild.props?.children ?? '').replace(/\n$/, '');

                        if (language === 'mermaid') {
                          return (
                            <MermaidDiagram
                              chart={codeString}
                              className="mb-6"
                            />
                          );
                        }

                        return (
                          <div style={{ marginBottom: '1.5rem' }}>
                            <SyntaxHighlighter
                              language={language}
                              style={vscDarkPlus}
                            >
                              {codeString}
                            </SyntaxHighlighter>
                          </div>
                        );
                      }

                      return <div style={{ marginBottom: '1.5rem' }}>{children}</div>;
                    },
                    code: ({ children, className, ...props }: any) => {
                      // Inline code only — block code is handled by `pre` above.
                      return (
                        <code
                          style={{
                            backgroundColor: 'var(--stash-bg-code)',
                            padding: '0.2em 0.4em',
                            borderRadius: '3px',
                            fontSize: '0.9em',
                          }}
                          {...props}
                        >
                          {children}
                        </code>
                      );
                    },
                    ul: ({ children }) => (
                      <ul style={{ marginBottom: '1.5rem', paddingLeft: '1.5rem' }}>{children}</ul>
                    ),
                    ol: ({ children }) => (
                      <ol style={{ marginBottom: '1.5rem', paddingLeft: '1.5rem' }}>{children}</ol>
                    ),
                    li: ({ children }) => (
                      <li style={{ marginBottom: '0.5rem' }}>{children}</li>
                    ),
                    a: ({ children, href }) => {
                      if (!href) {
                        return <span style={{ color: 'var(--stash-accent)' }}>{children}</span>;
                      }

                      // Anchor-only links scroll within the page
                      if (href.startsWith('#')) {
                        return (
                          <a
                            href={href}
                            style={{ color: 'var(--stash-accent)', textDecoration: 'underline', cursor: 'pointer' }}
                            onClick={(e) => {
                              e.preventDefault();
                              const id = href.slice(1);
                              const el = document.getElementById(id);
                              if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
                            }}
                          >
                            {children}
                          </a>
                        );
                      }

                      // External links open in a new tab
                      if (isExternalLink(href)) {
                        return (
                          <a
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: 'var(--stash-accent)', textDecoration: 'underline' }}
                          >
                            {children}
                          </a>
                        );
                      }

                      // Internal document links navigate within the app
                      const resolvedPath = file ? resolveInternalPath(href, file.path) : href;
                      return (
                        <a
                          href={href}
                          style={{ color: 'var(--stash-accent)', textDecoration: 'underline', cursor: 'pointer' }}
                          onClick={(e) => {
                            e.preventDefault();
                            if (onNavigate && resolvedPath) {
                              onNavigate(resolvedPath);
                            }
                          }}
                        >
                          {children}
                        </a>
                      );
                    },
                    table: ({ children }) => (
                      <table style={{
                        width: '100%',
                        marginBottom: '1.5rem',
                        borderCollapse: 'collapse',
                        border: '1px solid var(--stash-border)'
                      }}>
                        {children}
                      </table>
                    ),
                    th: ({ children }) => (
                      <th style={{
                        padding: '0.75rem',
                        borderBottom: '2px solid var(--stash-border)',
                        textAlign: 'left',
                        backgroundColor: 'var(--stash-bg-surface)'
                      }}>
                        {children}
                      </th>
                    ),
                    td: ({ children }) => (
                      <td style={{
                        padding: '0.75rem',
                        borderBottom: '1px solid var(--stash-border)'
                      }}>
                        {children}
                      </td>
                    ),
                    mermaid: ({ children }) => (
                      <MermaidDiagram
                        chart={String(children)}
                        style={{ marginBottom: '1.5rem' }}
                      />
                    ),
                  }}
                >
                  {file.content || ''}
                </ReactMarkdown>
              </div>
            ) : (
              <pre
                className="font-mono text-sm whitespace-pre-wrap"
                style={{
                  color: 'var(--stash-text-primary)',
                  lineHeight: '1.6'
                }}
              >
                {file.content || ''}
              </pre>
            )
          ) : (
            <div className="relative">
              <textarea
                value={editContent}
                onChange={(e) => handleContentChange(e.target.value)}
                className="w-full min-h-[600px] p-4 rounded-md font-mono text-sm resize-none outline-none"
                style={{
                  backgroundColor: 'var(--stash-bg-surface)',
                  color: 'var(--stash-text-primary)',
                  border: '1px solid var(--stash-border)',
                  lineHeight: '1.6'
                }}
              />
            </div>
          )}
        </div>
      </div>

      {/* Save Bar */}
      {hasChanges && mode === 'edit' && (
        <div
          className="sticky bottom-0 flex items-center justify-center gap-3 px-8 py-4 backdrop-blur-md"
          style={{
            backgroundColor: 'rgba(30, 30, 46, 0.95)',
            borderTop: '1px solid var(--stash-border)'
          }}
        >
          <button
            onClick={handleSave}
            className="flex items-center gap-2 px-6 py-2 rounded-md transition-all duration-150"
            style={{
              backgroundColor: 'var(--stash-accent)',
              color: 'var(--stash-bg-base)'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.opacity = '0.9';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = '1';
            }}
          >
            <Save className="w-4 h-4" />
            <span className="text-sm">Save</span>
          </button>
          <button
            onClick={handleDiscard}
            className="flex items-center gap-2 px-6 py-2 rounded-md transition-all duration-150"
            style={{
              backgroundColor: 'transparent',
              color: 'var(--stash-text-secondary)',
              border: '1px solid var(--stash-border)'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-surface)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <X className="w-4 h-4" />
            <span className="text-sm">Discard</span>
          </button>
        </div>
      )}
    </div>
  );
}