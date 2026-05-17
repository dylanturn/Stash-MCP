import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';
import { Code, ZoomIn, ZoomOut, RotateCcw, Download } from 'lucide-react';
import {
  TransformWrapper,
  TransformComponent,
  useControls,
  type ReactZoomPanPinchRef,
} from 'react-zoom-pan-pinch';
import { THEME_CHANGE_EVENT } from './AppearanceSettings';

interface MermaidDiagramProps {
  chart: string;
  className?: string;
}

/** Resolve a CSS custom property off the document root. Always returns
 * a usable color string — mermaid bakes these into the rendered SVG,
 * so empty values would produce broken diagrams. */
function readCssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return value || fallback;
}

/** Relative luminance for any CSS color string mermaid embeds in the
 * rendered SVG (``#rgb``, ``#rrggbb``, or ``rgb()``/``rgba()``).
 * Returns ``null`` for ``none`` / ``transparent`` / unparseable so
 * callers can leave text alone in that case. */
function parseLuminance(color: string): number | null {
  const c = color.trim().toLowerCase();
  if (!c || c === 'none' || c === 'transparent') return null;
  let r = 0;
  let g = 0;
  let b = 0;
  const longHex = c.match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/);
  const shortHex = c.match(/^#([0-9a-f])([0-9a-f])([0-9a-f])$/);
  const rgb = c.match(/^rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)/);
  if (longHex) {
    r = parseInt(longHex[1], 16);
    g = parseInt(longHex[2], 16);
    b = parseInt(longHex[3], 16);
  } else if (shortHex) {
    r = parseInt(shortHex[1] + shortHex[1], 16);
    g = parseInt(shortHex[2] + shortHex[2], 16);
    b = parseInt(shortHex[3] + shortHex[3], 16);
  } else if (rgb) {
    r = parseFloat(rgb[1]);
    g = parseFloat(rgb[2]);
    b = parseFloat(rgb[3]);
  } else {
    return null;
  }
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
}

function isDarkBg(hex: string): boolean {
  const lum = parseLuminance(hex);
  return lum === null ? true : lum < 0.5;
}

/** Mermaid bakes a single ``textColor`` into the SVG for all node
 * text, but a diagram author can override individual node fills with
 * ``classDef``. When that fill happens to clash with the theme's text
 * color (e.g. a pale ``classDef`` fill on a dark theme), the labels
 * become unreadable.
 *
 * This walks the rendered SVG, reads each node's actual ``fill``
 * (attribute or inline style), and forces the text inside to a
 * guaranteed-contrasting near-black or near-white. Always-fixed
 * contrast colors (not theme vars) so light/cream fills work on dark
 * themes too. */
function applyNodeTextContrast(svgMarkup: string): string {
  if (typeof DOMParser === 'undefined') return svgMarkup;
  const doc = new DOMParser().parseFromString(svgMarkup, 'image/svg+xml');
  if (doc.querySelector('parsererror')) return svgMarkup;

  // Mermaid emits ``<svg width="100%" style="max-width: Npx">`` —
  // inside ``react-zoom-pan-pinch``'s transformed content area, which
  // has no defined width, ``width="100%"`` resolves to 0px and the
  // SVG collapses to nothing. Rewrite to explicit viewBox dimensions
  // so the content component has a real natural size to measure
  // against when we call ``centerView()`` below.
  const svgRoot = doc.querySelector('svg');
  const vb = svgRoot?.viewBox?.baseVal;
  if (svgRoot && vb && vb.width > 0 && vb.height > 0) {
    svgRoot.setAttribute('width', String(vb.width));
    svgRoot.setAttribute('height', String(vb.height));
    const style = svgRoot.getAttribute('style') || '';
    const cleaned = style
      .replace(/(?:^|;)\s*max-width\s*:[^;]+/gi, '')
      .replace(/^\s*;\s*/, '')
      .trim();
    if (cleaned) svgRoot.setAttribute('style', cleaned);
    else svgRoot.removeAttribute('style');
  }

  const ON_LIGHT = '#11151c';
  const ON_DARK = '#e0e4f0';

  const nodes = doc.querySelectorAll(
    'g.node, g.actor, g.cluster, g.statediagram-cluster, g.classGroup',
  );
  nodes.forEach((node) => {
    const shape = node.querySelector(
      ':scope > rect, :scope > circle, :scope > polygon, :scope > path, :scope > ellipse, :scope > .basic, :scope > .label-container',
    ) as SVGElement | null;
    if (!shape) return;
    const inline = shape.getAttribute('style') || '';
    const fillFromStyle = inline.match(/(?:^|[;\s])fill\s*:\s*([^;]+)/i)?.[1];
    const fill = (fillFromStyle || shape.getAttribute('fill') || '').trim();
    const lum = parseLuminance(fill);
    if (lum === null) return;
    const textColor = lum > 0.55 ? ON_LIGHT : ON_DARK;

    node.querySelectorAll('text, tspan').forEach((el) => {
      (el as SVGElement).setAttribute('fill', textColor);
      // Some mermaid versions emit ``style="fill: …"`` too — keep
      // the attribute and inline style aligned.
      const existing = (el as SVGElement).getAttribute('style') || '';
      (el as SVGElement).setAttribute(
        'style',
        `${existing.replace(/(?:^|[;\s])fill\s*:[^;]+;?/i, '')};fill:${textColor}`,
      );
    });
    node
      .querySelectorAll('foreignObject div, foreignObject span, foreignObject p')
      .forEach((el) => {
        (el as HTMLElement).style.color = textColor;
      });
  });

  return new XMLSerializer().serializeToString(doc);
}

/** Map the active Stash theme vars to mermaid's ``themeVariables``.
 * Called on every render so theme swaps via ``applyTheme()`` flow
 * straight through.
 *
 * Node fills use surface/elevated backgrounds (not the accent), so
 * the same accent color works as a border across the whole palette
 * without sacrificing text contrast — the previous hardcoded mapping
 * filled nodes with ``--stash-accent`` and then tried to read text
 * against it, which only worked on the original teal-on-#1e1e2e
 * palette. */
function getMermaidThemeVariables() {
  const bgBase = readCssVar('--stash-bg-base', '#1e1e2e');
  const bgSurface = readCssVar('--stash-bg-surface', '#272738');
  const bgElevated = readCssVar('--stash-bg-elevated', '#2e2e42');
  const bgCode = readCssVar('--stash-bg-code', '#181825');
  const textPrimary = readCssVar('--stash-text-primary', '#cdd6f4');
  const textSecondary = readCssVar('--stash-text-secondary', '#7f849c');
  const textBright = readCssVar('--stash-text-bright', '#e0e4f0');
  const accent = readCssVar('--stash-accent', '#94e2d5');
  const destructive = readCssVar('--stash-destructive', '#f38ba8');
  const border = readCssVar('--stash-border', '#313244');
  const dark = isDarkBg(bgBase);

  return {
    darkMode: dark,
    background: bgBase,

    primaryColor: bgElevated,
    primaryTextColor: textPrimary,
    primaryBorderColor: accent,
    lineColor: textSecondary,
    secondaryColor: bgSurface,
    secondaryTextColor: textPrimary,
    secondaryBorderColor: border,
    tertiaryColor: bgCode,
    tertiaryTextColor: textPrimary,
    tertiaryBorderColor: border,

    textColor: textPrimary,
    fontSize: '16px',
    fontFamily: 'ui-sans-serif, system-ui, sans-serif',

    mainBkg: bgElevated,
    secondBkg: bgSurface,
    tertiaryBkg: bgCode,

    border1: border,
    border2: accent,

    nodeBorder: accent,
    nodeTextColor: textPrimary,
    clusterBkg: bgSurface,
    clusterBorder: border,
    defaultLinkColor: textSecondary,
    titleColor: textBright,
    edgeLabelBackground: bgBase,

    // Sequence diagrams
    actorBorder: accent,
    actorBkg: bgElevated,
    actorTextColor: textPrimary,
    actorLineColor: textSecondary,
    signalColor: textPrimary,
    signalTextColor: textPrimary,
    labelBoxBkgColor: bgElevated,
    labelBoxBorderColor: accent,
    labelTextColor: textPrimary,
    loopTextColor: textPrimary,
    noteBorderColor: accent,
    noteBkgColor: bgSurface,
    noteTextColor: textPrimary,
    activationBorderColor: accent,
    activationBkgColor: accent,
    sequenceNumberColor: bgBase,

    // State / class diagrams
    labelColor: textPrimary,
    classText: textPrimary,

    // Git graph — branch lanes rotate through the accent + a few
    // theme-neutral hues so multi-branch graphs stay legible. Branch
    // labels render against ``--stash-bg-base`` so they read the same
    // in light and dark themes.
    git0: accent,
    git1: textSecondary,
    git2: destructive,
    git3: textBright,
    git4: border,
    git5: accent,
    git6: textSecondary,
    git7: destructive,
    gitBranchLabel0: bgBase,
    gitBranchLabel1: bgBase,
    gitBranchLabel2: bgBase,
    gitBranchLabel3: bgBase,
    gitBranchLabel4: bgBase,
    gitBranchLabel5: bgBase,
    gitBranchLabel6: bgBase,
    gitBranchLabel7: bgBase,
    commitLabelColor: textPrimary,
    commitLabelBackground: bgElevated,

    // Pie charts
    pie1: accent,
    pie2: textSecondary,
    pie3: destructive,
    pie4: textBright,
    pie5: border,
    pie6: accent,
    pie7: textSecondary,
    pie8: destructive,
    pieTitleTextSize: '24px',
    pieTitleTextColor: textBright,
    pieSectionTextSize: '16px',
    pieSectionTextColor: textPrimary,
    pieLegendTextSize: '14px',
    pieLegendTextColor: textPrimary,
    pieStrokeColor: bgBase,
    pieStrokeWidth: '2px',
    pieOpacity: '0.95',

    // ER diagrams
    attributeBackgroundColorOdd: bgElevated,
    attributeBackgroundColorEven: bgSurface,
    entityBackgroundColor: bgElevated,
    entityBorderColor: accent,
    entityTextColor: textPrimary,
    relationLabelColor: textPrimary,
    relationLabelBackground: bgBase,
    relationColor: textSecondary,
    attributeTextColor: textPrimary,
    labelBackground: bgBase,
  };
}

function initializeMermaid() {
  mermaid.initialize({
    startOnLoad: false,
    theme: 'base',
    themeVariables: getMermaidThemeVariables(),
    fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    fontSize: 16,
    flowchart: { htmlLabels: true, curve: 'basis' },
    sequence: {
      diagramMarginX: 50,
      diagramMarginY: 10,
      actorMargin: 50,
      width: 150,
      height: 65,
      boxMargin: 10,
      boxTextMargin: 5,
      noteMargin: 10,
      messageMargin: 35,
      mirrorActors: true,
      useMaxWidth: true,
    },
    gantt: {
      titleTopMargin: 25,
      barHeight: 20,
      barGap: 4,
      topPadding: 50,
      leftPadding: 75,
      gridLineStartPadding: 35,
      fontSize: 11,
      numberSectionStyles: 4,
      axisFormat: '%Y-%m-%d',
    },
  });
}

initializeMermaid();

// Controls component that uses the useControls hook
function DiagramControls({ onDownload }: { onDownload: () => void }) {
  const { zoomIn, zoomOut, resetTransform } = useControls();

  return (
    <div
      className="absolute top-3 right-3 flex items-center gap-1 p-1 rounded-lg shadow-lg"
      style={{
        backgroundColor: 'var(--stash-bg-elevated)',
        border: '1px solid var(--stash-border)',
        zIndex: 10,
      }}
    >
      <button
        onClick={() => zoomIn()}
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
        title="Zoom in"
      >
        <ZoomIn className="w-4 h-4" />
      </button>
      <button
        onClick={() => zoomOut()}
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
        title="Zoom out"
      >
        <ZoomOut className="w-4 h-4" />
      </button>
      <button
        onClick={() => resetTransform()}
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
        title="Reset zoom"
      >
        <RotateCcw className="w-4 h-4" />
      </button>
      <div
        style={{
          width: '1px',
          height: '20px',
          backgroundColor: 'var(--stash-border)',
          margin: '0 2px',
        }}
      />
      <button
        onClick={onDownload}
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
        title="Download SVG"
      >
        <Download className="w-4 h-4" />
      </button>
    </div>
  );
}

export function MermaidDiagram({ chart, className = '' }: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const transformApiRef = useRef<ReactZoomPanPinchRef | null>(null);
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [showSource, setShowSource] = useState(false);
  // Bumped on theme swaps to force a re-init + re-render of the SVG.
  // Mermaid bakes colors into the SVG at render time, so swapping
  // CSS vars alone won't re-color an already-rendered diagram.
  const [themeNonce, setThemeNonce] = useState(0);

  useEffect(() => {
    const handler = () => setThemeNonce((n) => n + 1);
    window.addEventListener(THEME_CHANGE_EVENT, handler);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, handler);
  }, []);

  // Fit-on-load: measure the rendered SVG against the viewport and
  // pick an initial zoom so small diagrams stay at 1:1 (don't blow up
  // to fill 500px of vertical space) while large diagrams scale down
  // to fit. Runs after every re-render of the SVG markup, including
  // theme swaps and ``showSource`` toggles. The user's manual
  // zoom/pan resets when the SVG itself changes — re-fitting is the
  // intended behaviour, otherwise stale transforms would point at
  // empty space.
  useEffect(() => {
    if (!svg) return;
    const raf = requestAnimationFrame(() => {
      const api = transformApiRef.current;
      const viewport = viewportRef.current;
      const svgEl = containerRef.current?.querySelector('svg');
      if (!api || !viewport || !svgEl) return;
      const vb = svgEl.viewBox?.baseVal;
      const naturalW = vb && vb.width
        ? vb.width
        : svgEl.getBoundingClientRect().width;
      const naturalH = vb && vb.height
        ? vb.height
        : svgEl.getBoundingClientRect().height;
      if (!naturalW || !naturalH) return;
      // 0.95 leaves a little breathing room around the diagram so it
      // doesn't kiss the viewport edges. Capped at 1.0 so a 2-node
      // flowchart doesn't render with 80px text.
      const fit = Math.min(
        viewport.offsetWidth / naturalW,
        viewport.offsetHeight / naturalH,
        1,
      );
      const scale = Math.max(fit * 0.95, 0.1);
      api.centerView(scale, 0);
    });
    return () => cancelAnimationFrame(raf);
  }, [svg]);

  const handleDownload = () => {
    const svgData = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(svgData);
    const link = document.createElement('a');
    link.href = url;
    link.download = `mermaid-diagram-${Date.now()}.svg`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  useEffect(() => {
    const renderDiagram = async () => {
      if (!containerRef.current) return;

      try {
        setError('');
        // Re-init with the current theme vars so a swap takes effect
        // here even when the module-level call ran with an earlier
        // palette.
        initializeMermaid();
        const id = `mermaid-${Math.random().toString(36).substr(2, 9)}`;

        const { svg: renderedSvg } = await mermaid.render(id, chart);

        // Layer a small theme-aware stylesheet on top of mermaid's
        // output. ``themeVariables`` covers most of the palette, but
        // a few diagram types (timeline, gantt) inline classes that
        // need an explicit fill against their accent-tinted bars.
        // Node label text is handled per-node by ``applyNodeTextContrast``
        // (further down) so authored ``classDef`` fills get a
        // contrast-matched text color regardless of the active theme.
        const bgBase = readCssVar('--stash-bg-base', '#1e1e2e');
        const textPrimary = readCssVar('--stash-text-primary', '#cdd6f4');
        const textBright = readCssVar('--stash-text-bright', '#e0e4f0');
        const overrides = `
            /* Timeline event labels render on accent-colored fills —
             * force a dark on-color so they stay legible on light themes
             * too. Section titles read against the page background. */
            .timeline .event rect + text,
            .timeline text {
              fill: ${bgBase} !important;
              font-weight: 600 !important;
            }
            .timeline .section0 text,
            .timeline .section1 text,
            .timeline .section2 text,
            .timeline .section3 text,
            .timeline .section {
              fill: ${textBright} !important;
              font-weight: 700 !important;
              font-size: 18px !important;
            }

            /* Gantt task labels sit on filled bars (always tinted by
             * the active accent), axis labels sit on the page. */
            .taskText,
            .taskTextOutsideRight,
            .taskTextOutsideLeft,
            .taskText0,
            .taskText1,
            .taskText2,
            .taskText3,
            .sectionTitle,
            .titleText {
              fill: ${bgBase} !important;
              font-weight: 500 !important;
            }
            .tick text {
              fill: ${textPrimary} !important;
            }

            /* Edge labels sit on the page background, not on a node fill. */
            .edgeLabel,
            .edgeLabel text {
              color: ${textPrimary};
              fill: ${textPrimary};
            }
          `;
        const styledSvg = renderedSvg.replace(/<style>/, `<style>${overrides}`);
        const fixedSvg = applyNodeTextContrast(styledSvg);

        setSvg(fixedSvg);
      } catch (err) {
        console.error('Mermaid rendering error:', err);
        setError(err instanceof Error ? err.message : 'Failed to render diagram');
      }
    };

    renderDiagram();
  }, [chart, themeNonce]);

  if (error) {
    return (
      <div
        className={`rounded-lg border p-4 ${className}`}
        style={{
          backgroundColor: 'var(--stash-bg-surface)',
          borderColor: 'var(--stash-destructive)',
        }}
      >
        <div className="flex items-start gap-2 mb-2">
          <div
            className="px-2 py-1 rounded text-xs font-medium"
            style={{
              backgroundColor: 'rgba(243, 139, 168, 0.2)',
              color: 'var(--stash-destructive)',
            }}
          >
            Mermaid Error
          </div>
        </div>
        <pre
          className="text-xs whitespace-pre-wrap font-mono"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          {error}
        </pre>
        <details className="mt-3">
          <summary
            className="cursor-pointer text-xs"
            style={{ color: 'var(--stash-text-secondary)' }}
          >
            Show source
          </summary>
          <pre
            className="mt-2 p-2 rounded text-xs whitespace-pre-wrap font-mono"
            style={{
              backgroundColor: 'var(--stash-bg-code)',
              color: 'var(--stash-text-secondary)',
            }}
          >
            {chart}
          </pre>
        </details>
      </div>
    );
  }

  return (
    <div
      className={`rounded-lg border overflow-hidden ${className}`}
      style={{
        backgroundColor: 'var(--stash-bg-surface)',
        borderColor: 'var(--stash-border)',
      }}
    >
      {/* Header with source toggle */}
      <div
        className="px-4 py-2 border-b flex items-center justify-between"
        style={{ borderColor: 'var(--stash-border)' }}
      >
        <div className="flex items-center gap-2">
          <Code className="w-3.5 h-3.5" style={{ color: 'var(--stash-accent)' }} />
          <span className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
            Mermaid Diagram
          </span>
        </div>
        <button
          onClick={() => setShowSource(!showSource)}
          className="text-xs px-2 py-1 rounded transition-colors duration-150"
          style={{
            color: showSource ? 'var(--stash-accent)' : 'var(--stash-text-secondary)',
          }}
          onMouseEnter={(e) => {
            if (!showSource) {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
            }
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent';
          }}
        >
          {showSource ? 'Hide' : 'Show'} Source
        </button>
      </div>

      {/* Source code (when toggled) */}
      {showSource && (
        <div
          className="px-4 py-3 border-b"
          style={{ borderColor: 'var(--stash-border)' }}
        >
          <pre
            className="text-xs whitespace-pre-wrap font-mono"
            style={{
              color: 'var(--stash-text-secondary)',
            }}
          >
            {chart}
          </pre>
        </div>
      )}

      {/* Rendered diagram with zoom controls */}
      <div ref={viewportRef} className="relative" style={{ minHeight: '500px' }}>
        <TransformWrapper
          ref={transformApiRef}
          initialScale={1}
          minScale={0.1}
          maxScale={5}
          centerOnInit
          wheel={{ step: 0.05 }}
          doubleClick={{ disabled: false, mode: 'zoomIn', step: 0.7 }}
          panning={{ velocityDisabled: true }}
        >
          {() => (
            <>
              <DiagramControls onDownload={handleDownload} />
              <TransformComponent
                wrapperStyle={{
                  width: '100%',
                  height: '500px',
                  backgroundColor: 'var(--stash-bg-surface)',
                }}
                contentStyle={{
                  width: '100%',
                  height: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <div
                  ref={containerRef}
                  className="p-6"
                  dangerouslySetInnerHTML={{ __html: svg }}
                />
              </TransformComponent>
            </>
          )}
        </TransformWrapper>
      </div>
    </div>
  );
}