import { useEffect, useState } from 'react';

export type BinaryKind = 'image' | 'pdf' | 'html';

const IMAGE_EXTS = new Set([
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico', 'bmp', 'avif',
]);

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
  /** URL serving raw bytes for image / pdf. */
  rawUrl: string;
  /** Inline HTML text (for `kind === 'html'`). The HTML renders in a
   * sandboxed iframe so it can't reach the parent origin's cookies or
   * APIs. */
  htmlContent?: string;
  fileName: string;
}

/** Renders images, PDFs, and HTML artifacts inside the document
 * viewport. Images and PDFs stream from the API's raw endpoint;
 * HTML is injected via ``iframe srcDoc`` with a strict sandbox so
 * the artifact runs in a null origin. */
export function BinaryFileViewer({ kind, rawUrl, htmlContent, fileName }: BinaryFileViewerProps) {
  if (kind === 'image') {
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
