import { useEffect, useRef, useState } from 'react';
import { Code, Download, ExternalLink, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react';
import {
  TransformComponent,
  TransformWrapper,
  useControls,
  type ReactZoomPanPinchRef,
} from 'react-zoom-pan-pinch';

export type BinaryKind = 'image' | 'pdf' | 'html';

const IMAGE_EXTS = new Set([
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico', 'bmp', 'avif',
]);

/** Map extension → MIME type for the file kinds the binary viewer
 * handles. Mirrors ``stash_mcp/mcp_server.py``'s ``MIME_TYPES`` for
 * these extensions so the client can populate the metadata panel
 * without an extra round-trip when a binary file is selected (which
 * skips the JSON content fetch). */
const BINARY_MIME_BY_EXT: Record<string, string> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  webp: 'image/webp',
  avif: 'image/avif',
  svg: 'image/svg+xml',
  ico: 'image/x-icon',
  bmp: 'image/bmp',
  pdf: 'application/pdf',
  html: 'text/html',
  htm: 'text/html',
};

export function mimeTypeForBinary(extension: string | undefined): string | undefined {
  if (!extension) return undefined;
  return BINARY_MIME_BY_EXT[extension.toLowerCase()];
}

/** Classify a file as image / pdf / html / null based on extension.
 *
 * SVG renders inline as an image rather than via an HTML iframe so the
 * file's `<script>` tags (if any) don't execute against the same origin
 * as the rest of the app. */
export function classifyBinary(extension: string | undefined): BinaryKind | null {
  if (!extension) return null;
  const ext = extension.toLowerCase();
  if (IMAGE_EXTS.has(ext)) return 'image';
  if (ext === 'pdf') return 'pdf';
  if (ext === 'html' || ext === 'htm') return 'html';
  return null;
}

interface BinaryFileViewerProps {
  kind: BinaryKind;
  /** URL serving raw bytes for image / pdf. Omitted when the caller
   * cannot build a raw URL (e.g. an API client without
   * ``rawUrl()``) — the viewer then renders an explicit unsupported
   * state instead of an ``<img src="">`` that would resolve to the
   * current page. */
  rawUrl?: string;
  /** Inline HTML text (for `kind === 'html'`). The HTML renders in a
   * sandboxed iframe so it can't reach the parent origin's cookies or
   * APIs. */
  htmlContent?: string;
  fileName: string;
  /** File extension — used by the image viewer to detect SVG (text
   * image) so the source-toggle button is offered. */
  extension?: string;
}

/** Renders images, PDFs, and HTML artifacts inside the document
 * viewport. Images and PDFs stream from the API's raw endpoint;
 * HTML is wrapped in a same-document blob URL and loaded into an
 * iframe with a strict ``sandbox`` so the artifact runs in a null
 * origin — blob URLs replace the legacy ``srcDoc`` approach to avoid
 * its length cap and per-keystroke re-render. */
export function BinaryFileViewer({
  kind,
  rawUrl,
  htmlContent,
  fileName,
  extension,
}: BinaryFileViewerProps) {
  if (kind === 'image') {
    if (!rawUrl) return <UnavailableState reason="image" />;
    const isSvg = (extension || '').toLowerCase() === 'svg';
    return <ImageViewer src={rawUrl} alt={fileName} isSvg={isSvg} />;
  }

  if (kind === 'pdf') {
    if (!rawUrl) return <UnavailableState reason="pdf" />;
    return (
      <div className="h-full w-full" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <iframe
          src={rawUrl}
          title={fileName}
          style={{
            width: '100%',
            height: '100%',
            border: 'none',
            backgroundColor: '#ffffff',
          }}
        />
      </div>
    );
  }

  if (kind === 'html') {
    // `allow-scripts` lets Claude artifacts run their JS; the
    // sandbox without `allow-same-origin` puts the iframe in a null
    // origin, so it can't read parent cookies or call the Stash API.
    return (
      <HtmlViewer html={htmlContent || ''} title={fileName} rawUrl={rawUrl} />
    );
  }

  return null;
}

function UnavailableState({ reason }: { reason: 'image' | 'pdf' }) {
  const label = reason === 'image' ? 'image' : 'PDF';
  return (
    <div
      className="h-full w-full flex items-center justify-center p-8 text-center"
      style={{ backgroundColor: 'var(--stash-bg-base)', color: 'var(--stash-text-secondary)' }}
    >
      <div>
        <div className="text-sm font-medium" style={{ color: 'var(--stash-text-primary)' }}>
          {label} preview unavailable
        </div>
        <div className="text-xs mt-1">
          The API client cannot construct a raw URL for this file.
        </div>
      </div>
    </div>
  );
}

/** Zoom/pan-capable image viewer. Bitmap images and SVG share the
 * same render path (``<img src="...">``) — SVGs additionally expose
 * a "Show source" toggle that lazy-fetches the SVG markup so the user
 * can inspect the raw XML. */
function ImageViewer({ src, alt, isSvg }: { src: string; alt: string; isSvg: boolean }) {
  const [showSource, setShowSource] = useState(false);
  const [source, setSource] = useState<string | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const transformRef = useRef<ReactZoomPanPinchRef | null>(null);

  // Lazy-load SVG source the first time the toggle is flipped on. The
  // markup comes from the same raw endpoint the ``<img>`` already
  // uses, so the second request hits the browser cache.
  useEffect(() => {
    if (!showSource || !isSvg || source !== null || sourceError !== null) return;
    let cancelled = false;
    fetch(src)
      .then((res) => {
        if (!res.ok) throw new Error(`Fetch failed: ${res.status}`);
        return res.text();
      })
      .then((text) => {
        if (!cancelled) setSource(text);
      })
      .catch((err) => {
        if (!cancelled) setSourceError(err?.message || 'Failed to load SVG source');
      });
    return () => {
      cancelled = true;
    };
  }, [showSource, isSvg, src, source, sourceError]);

  return (
    <div
      className="h-full w-full flex flex-col"
      style={{ backgroundColor: 'var(--stash-bg-base)' }}
    >
      {/* Toolbar */}
      <div
        className="px-4 py-2 border-b flex items-center justify-between"
        style={{ borderColor: 'var(--stash-border)' }}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
            {isSvg ? 'SVG' : 'Image'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {isSvg && (
            <button
              onClick={() => setShowSource((v) => !v)}
              className="text-xs px-2 py-1 rounded transition-colors duration-150 flex items-center gap-1"
              style={{
                color: showSource ? 'var(--stash-accent)' : 'var(--stash-text-secondary)',
              }}
              title={showSource ? 'Hide source' : 'Show source'}
            >
              <Code className="w-3.5 h-3.5" />
              {showSource ? 'Hide' : 'Show'} Source
            </button>
          )}
          <a
            href={src}
            download={alt}
            className="text-xs p-1.5 rounded transition-colors duration-150"
            style={{ color: 'var(--stash-text-secondary)' }}
            title="Download"
          >
            <Download className="w-4 h-4" />
          </a>
        </div>
      </div>

      {showSource && isSvg ? (
        <div className="flex-1 overflow-auto">
          {source !== null ? (
            <pre
              className="text-xs font-mono whitespace-pre-wrap p-4"
              style={{ color: 'var(--stash-text-primary)' }}
            >
              {source}
            </pre>
          ) : sourceError ? (
            <div
              className="p-4 text-sm"
              style={{ color: 'var(--stash-destructive)' }}
            >
              {sourceError}
            </div>
          ) : (
            <div
              className="p-4 text-sm"
              style={{ color: 'var(--stash-text-secondary)' }}
            >
              Loading source…
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 relative" style={{ minHeight: 0 }}>
          <TransformWrapper
            ref={transformRef}
            initialScale={1}
            minScale={0.1}
            maxScale={10}
            centerOnInit
            limitToBounds={false}
            wheel={{ step: 0.1 }}
            doubleClick={{ disabled: false, mode: 'zoomIn', step: 0.7 }}
          >
            {() => (
              <>
                <ImageZoomControls onReset={() => transformRef.current?.resetTransform()} />
                <TransformComponent
                  wrapperStyle={{
                    width: '100%',
                    height: '100%',
                    backgroundColor: 'var(--stash-bg-base)',
                  }}
                  contentStyle={{
                    width: '100%',
                    height: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <img
                    src={src}
                    alt={alt}
                    draggable={false}
                    style={{
                      maxWidth: '100%',
                      maxHeight: '100%',
                      objectFit: 'contain',
                      boxShadow: '0 4px 24px rgba(0, 0, 0, 0.4)',
                      backgroundColor: 'var(--stash-bg-surface)',
                    }}
                  />
                </TransformComponent>
              </>
            )}
          </TransformWrapper>
        </div>
      )}
    </div>
  );
}

function ImageZoomControls({ onReset }: { onReset: () => void }) {
  const { zoomIn, zoomOut } = useControls();
  return (
    <div
      className="absolute top-3 right-3 flex items-center gap-1 p-1 rounded-lg shadow-lg"
      style={{
        backgroundColor: 'var(--stash-bg-elevated)',
        border: '1px solid var(--stash-border)',
        zIndex: 10,
      }}
    >
      <ToolbarBtn onClick={() => zoomIn()} title="Zoom in">
        <ZoomIn className="w-4 h-4" />
      </ToolbarBtn>
      <ToolbarBtn onClick={() => zoomOut()} title="Zoom out">
        <ZoomOut className="w-4 h-4" />
      </ToolbarBtn>
      <ToolbarBtn onClick={onReset} title="Reset zoom">
        <RotateCcw className="w-4 h-4" />
      </ToolbarBtn>
    </div>
  );
}

function ToolbarBtn({
  onClick,
  title,
  children,
}: {
  onClick: () => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="p-1.5 rounded transition-colors duration-150"
      style={{ color: 'var(--stash-text-secondary)' }}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
        e.currentTarget.style.color = 'var(--stash-accent)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = 'transparent';
        e.currentTarget.style.color = 'var(--stash-text-secondary)';
      }}
      title={title}
    >
      {children}
    </button>
  );
}

/** HTML artifact viewer with a Rendered / Source toggle. The rendered
 * view runs in a sandboxed iframe with a null origin; the source view
 * shows the raw markup as syntax-neutral monospace text. */
function HtmlViewer({
  html,
  title,
  rawUrl,
}: {
  html: string;
  title: string;
  rawUrl?: string;
}) {
  const [view, setView] = useState<'rendered' | 'source'>('rendered');
  return (
    <div
      className="h-full w-full flex flex-col"
      style={{ backgroundColor: 'var(--stash-bg-base)' }}
    >
      <div
        className="px-4 py-2 border-b flex items-center justify-between"
        style={{ borderColor: 'var(--stash-border)' }}
      >
        <div className="flex items-center gap-1">
          <button
            onClick={() => setView('rendered')}
            className="text-xs px-2 py-1 rounded transition-colors duration-150"
            style={{
              color: view === 'rendered' ? 'var(--stash-accent)' : 'var(--stash-text-secondary)',
            }}
          >
            Rendered
          </button>
          <button
            onClick={() => setView('source')}
            className="text-xs px-2 py-1 rounded transition-colors duration-150 flex items-center gap-1"
            style={{
              color: view === 'source' ? 'var(--stash-accent)' : 'var(--stash-text-secondary)',
            }}
          >
            <Code className="w-3.5 h-3.5" />
            Source
          </button>
        </div>
        {rawUrl && (
          <a
            href={rawUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs p-1.5 rounded transition-colors duration-150"
            style={{ color: 'var(--stash-text-secondary)' }}
            title="Open raw HTML in new tab"
          >
            <ExternalLink className="w-4 h-4" />
          </a>
        )}
      </div>
      <div className="flex-1" style={{ minHeight: 0 }}>
        {view === 'rendered' ? (
          <HtmlSandboxFrame html={html} title={title} />
        ) : (
          <pre
            className="text-xs font-mono whitespace-pre-wrap p-4 h-full overflow-auto"
            style={{ color: 'var(--stash-text-primary)' }}
          >
            {html}
          </pre>
        )}
      </div>
    </div>
  );
}

function HtmlSandboxFrame({ html, title }: { html: string; title: string }) {
  // srcDoc has a length cap in some browsers and re-renders the whole
  // document on every keystroke when the editor is open. Use a blob
  // URL so the iframe loads once and large artifacts work reliably.
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [html]);

  return (
    <div className="h-full w-full" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
      {src && (
        <iframe
          src={src}
          title={title}
          sandbox="allow-scripts allow-forms allow-popups allow-modals"
          style={{
            width: '100%',
            height: '100%',
            border: 'none',
            backgroundColor: '#ffffff',
          }}
        />
      )}
    </div>
  );
}
