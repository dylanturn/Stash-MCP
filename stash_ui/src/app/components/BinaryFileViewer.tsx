import { useEffect, useState } from 'react';

export type BinaryKind = 'image' | 'pdf' | 'html' | 'svg';

const IMAGE_EXTS = new Set([
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'ico', 'bmp', 'avif',
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

/** Classify a file as image / pdf / html / svg / null based on extension.
 *
 * SVG is split out from raster images because it round-trips through
 * the JSON content endpoint as text — that lets the viewer render the
 * in-memory document (so unsaved edits preview live) and lets the
 * caller swap into an edit textarea. The rendered preview still goes
 * through an `<img>` element with a blob URL so any embedded
 * `<script>` tags stay inert. */
export function classifyBinary(extension: string | undefined): BinaryKind | null {
  if (!extension) return null;
  const ext = extension.toLowerCase();
  if (ext === 'svg') return 'svg';
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
  /** Inline SVG text (for `kind === 'svg'`). Rendered via a blob URL
   * in an `<img>` element so unsaved edits preview live without
   * letting the SVG's `<script>` tags run against the parent origin. */
  svgContent?: string;
  fileName: string;
}

/** Renders images, PDFs, and HTML artifacts inside the document
 * viewport. Images and PDFs stream from the API's raw endpoint;
 * HTML is wrapped in a same-document blob URL and loaded into an
 * iframe with a strict ``sandbox`` so the artifact runs in a null
 * origin — blob URLs replace the legacy ``srcDoc`` approach to avoid
 * its length cap and per-keystroke re-render. */
export function BinaryFileViewer({ kind, rawUrl, htmlContent, svgContent, fileName }: BinaryFileViewerProps) {
  if (kind === 'svg') {
    return <SvgPreview content={svgContent ?? ''} rawUrl={rawUrl} fileName={fileName} />;
  }
  if (kind === 'image') {
    if (!rawUrl) return <UnavailableState reason="image" />;
    return (
      <div
        className="h-full w-full flex items-center justify-center overflow-auto p-8"
        style={{ backgroundColor: 'var(--stash-bg-base)' }}
      >
        <img
          src={rawUrl}
          alt={fileName}
          style={{
            maxWidth: '100%',
            maxHeight: '100%',
            objectFit: 'contain',
            boxShadow: '0 4px 24px rgba(0, 0, 0, 0.4)',
            backgroundColor: 'var(--stash-bg-surface)',
          }}
        />
      </div>
    );
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
      <HtmlSandboxFrame html={htmlContent || ''} title={fileName} />
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

function SvgPreview({
  content,
  rawUrl,
  fileName,
}: {
  content: string;
  rawUrl?: string;
  fileName: string;
}) {
  // Prefer rendering from the in-memory document so unsaved edits
  // preview live. Fall back to the raw URL only when the editor
  // hasn't yet provided content (e.g. file is still loading).
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    if (!content) {
      setSrc(null);
      return;
    }
    const blob = new Blob([content], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    setSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [content]);

  const imgSrc = src ?? rawUrl;
  if (!imgSrc) return <UnavailableState reason="image" />;

  return (
    <div
      className="h-full w-full flex items-center justify-center overflow-auto p-8"
      style={{ backgroundColor: 'var(--stash-bg-base)' }}
    >
      <img
        src={imgSrc}
        alt={fileName}
        style={{
          maxWidth: '100%',
          maxHeight: '100%',
          objectFit: 'contain',
          boxShadow: '0 4px 24px rgba(0, 0, 0, 0.4)',
          backgroundColor: 'var(--stash-bg-surface)',
        }}
      />
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
