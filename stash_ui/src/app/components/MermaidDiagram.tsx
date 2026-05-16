import React, { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';
import { Code, ZoomIn, ZoomOut, RotateCcw, Download } from 'lucide-react';
import { TransformWrapper, TransformComponent, useControls } from 'react-zoom-pan-pinch';

interface MermaidDiagramProps {
  chart: string;
  className?: string;
}

// Initialize mermaid with Stash-MCP dark theme
mermaid.initialize({
  startOnLoad: false,
  theme: 'base',
  themeVariables: {
    // Core colors
    darkMode: true,
    background: '#1e1e2e',
    primaryColor: '#94e2d5',
    primaryTextColor: '#1e1e2e',
    primaryBorderColor: '#94e2d5',
    lineColor: '#94e2d5',
    secondaryColor: '#89dceb',
    secondaryTextColor: '#1e1e2e',
    secondaryBorderColor: '#89dceb',
    tertiaryColor: '#cba6f7',
    tertiaryTextColor: '#1e1e2e',
    tertiaryBorderColor: '#cba6f7',
    
    // Text colors
    textColor: '#cdd6f4',
    fontSize: '16px',
    fontFamily: 'ui-sans-serif, system-ui, sans-serif',
    
    // Background colors
    mainBkg: '#2e2e42',
    secondBkg: '#272738',
    tertiaryBkg: '#353550',
    
    // Border colors
    border1: '#94e2d5',
    border2: '#89dceb',
    
    // Node/box styling
    nodeBorder: '#94e2d5',
    nodeTextColor: '#cdd6f4',
    clusterBkg: '#272738',
    clusterBorder: '#94e2d5',
    defaultLinkColor: '#94e2d5',
    titleColor: '#cdd6f4',
    edgeLabelBackground: '#1e1e2e',
    
    // Specific diagram colors - Sequence Diagrams
    actorBorder: '#94e2d5',
    actorBkg: '#2e2e42',
    actorTextColor: '#cdd6f4',
    actorLineColor: '#94e2d5',
    signalColor: '#cdd6f4',
    signalTextColor: '#cdd6f4',
    labelBoxBkgColor: '#2e2e42',
    labelBoxBorderColor: '#94e2d5',
    labelTextColor: '#cdd6f4',
    loopTextColor: '#cdd6f4',
    noteBorderColor: '#f9e2af',
    noteBkgColor: '#2e2e42',
    noteTextColor: '#f9e2af',
    activationBorderColor: '#94e2d5',
    activationBkgColor: '#94e2d5',
    sequenceNumberColor: '#1e1e2e',
    
    // State diagram
    labelColor: '#1e1e2e',
    
    // Git graph
    git0: '#94e2d5',
    git1: '#89dceb',
    git2: '#f38ba8',
    git3: '#f9e2af',
    git4: '#cba6f7',
    git5: '#a6e3a1',
    git6: '#fab387',
    git7: '#f5c2e7',
    gitBranchLabel0: '#1e1e2e',
    gitBranchLabel1: '#1e1e2e',
    gitBranchLabel2: '#1e1e2e',
    gitBranchLabel3: '#1e1e2e',
    gitBranchLabel4: '#1e1e2e',
    gitBranchLabel5: '#1e1e2e',
    gitBranchLabel6: '#1e1e2e',
    gitBranchLabel7: '#1e1e2e',
    gitInv0: '#1e1e2e',
    gitInv1: '#1e1e2e',
    gitInv2: '#1e1e2e',
    gitInv3: '#1e1e2e',
    gitInv4: '#1e1e2e',
    gitInv5: '#1e1e2e',
    gitInv6: '#1e1e2e',
    gitInv7: '#1e1e2e',
    commitLabelColor: '#cdd6f4',
    commitLabelBackground: '#2e2e42',
    
    // Pie chart
    pie1: '#94e2d5',
    pie2: '#89dceb',
    pie3: '#f38ba8',
    pie4: '#f9e2af',
    pie5: '#cba6f7',
    pie6: '#a6e3a1',
    pie7: '#fab387',
    pie8: '#f5c2e7',
    pie9: '#b4befe',
    pie10: '#f2cdcd',
    pie11: '#eba0ac',
    pie12: '#74c7ec',
    pieTitleTextSize: '24px',
    pieTitleTextColor: '#cdd6f4',
    pieSectionTextSize: '16px',
    pieSectionTextColor: '#1e1e2e',
    pieLegendTextSize: '14px',
    pieLegendTextColor: '#cdd6f4',
    pieStrokeColor: '#1e1e2e',
    pieStrokeWidth: '2px',
    pieOpacity: '0.95',
    
    // Flowchart
    fillType0: '#94e2d5',
    fillType1: '#89dceb',
    fillType2: '#cba6f7',
    fillType3: '#f9e2af',
    fillType4: '#a6e3a1',
    fillType5: '#fab387',
    fillType6: '#f38ba8',
    fillType7: '#f5c2e7',
    
    // Class diagram
    classText: '#1e1e2e',
    
    // ER diagram
    attributeBackgroundColorOdd: '#2e2e42',
    attributeBackgroundColorEven: '#272738',
    entityBackgroundColor: '#2e2e42',
    entityBorderColor: '#94e2d5',
    entityTextColor: '#cdd6f4',
    relationLabelColor: '#cdd6f4',
    relationLabelBackground: '#1e1e2e',
    relationColor: '#94e2d5',
    attributeTextColor: '#cdd6f4',
    labelBackground: '#1e1e2e',
    
    // Timeline
    cScale0: '#94e2d5',
    cScale1: '#2e2e42',
    cScale2: '#89dceb',
    cScale3: '#2e2e42',
    cScale4: '#f38ba8',
    cScale5: '#2e2e42',
    cScale6: '#f9e2af',
    cScale7: '#2e2e42',
    cScale8: '#cba6f7',
    cScale9: '#2e2e42',
    cScale10: '#a6e3a1',
    cScale11: '#2e2e42',
    cScaleLabel0: '#1e1e2e',
    cScaleLabel1: '#cdd6f4',
    cScaleLabel2: '#1e1e2e',
    cScaleLabel3: '#cdd6f4',
    cScaleLabel4: '#1e1e2e',
    cScaleLabel5: '#cdd6f4',
    cScaleLabel6: '#1e1e2e',
    cScaleLabel7: '#cdd6f4',
    cScaleLabel8: '#1e1e2e',
    cScaleLabel9: '#cdd6f4',
    cScaleLabel10: '#1e1e2e',
    cScaleLabel11: '#cdd6f4',
  },
  fontFamily: 'ui-sans-serif, system-ui, sans-serif',
  fontSize: 16,
  flowchart: {
    htmlLabels: true,
    curve: 'basis',
  },
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
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [showSource, setShowSource] = useState(false);

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
        const id = `mermaid-${Math.random().toString(36).substr(2, 9)}`;
        
        const { svg: renderedSvg } = await mermaid.render(id, chart);
        
        // Apply comprehensive CSS fixes for text visibility across all diagram types
        let fixedSvg = renderedSvg;
        
        // Force text color to be visible across ALL diagram types
        fixedSvg = fixedSvg.replace(
          /<style>/,
          `<style>
            /* Universal text visibility fixes */
            text {
              fill: #cdd6f4 !important;
            }
            
            /* Timeline - ensure text visibility in boxes */
            .timeline .event rect + text,
            .timeline text {
              fill: #1e1e2e !important;
              font-weight: 600 !important;
            }
            
            /* Timeline section titles */
            .timeline .section0 text,
            .timeline .section1 text,
            .timeline .section2 text,
            .timeline .section3 text,
            .timeline .section {
              fill: #cdd6f4 !important;
              font-weight: 700 !important;
              font-size: 18px !important;
            }
            
            /* Gantt Charts - specific fixes for task labels */
            .taskText,
            .taskTextOutsideRight,
            .taskTextOutsideLeft,
            .taskText0,
            .taskText1,
            .taskText2,
            .taskText3,
            .sectionTitle,
            .titleText {
              fill: #1e1e2e !important;
              font-weight: 500 !important;
            }
            
            /* Gantt axis labels */
            .tick text {
              fill: #cdd6f4 !important;
            }
            
            /* ER Diagrams */
            .er.attributeBoxOdd text, 
            .er.attributeBoxEven text,
            .er .entityLabel text,
            .er text {
              fill: #cdd6f4 !important;
            }
            
            /* State Diagrams */
            .statediagram-state rect.basic + text,
            .statediagram-state text,
            g.stateGroup text,
            .state-note text {
              fill: #cdd6f4 !important;
            }
            
            /* Flowcharts */
            .node text,
            .nodeLabel,
            .edgeLabel text,
            foreignObject div {
              color: #cdd6f4 !important;
              fill: #cdd6f4 !important;
            }
            
            /* Class Diagrams */
            .classLabel text,
            .classTitle text {
              fill: #cdd6f4 !important;
            }
            
            /* Edge labels and transitions */
            .edgeLabel,
            .transition text {
              fill: #cdd6f4 !important;
            }
            
            /* Cluster/Subgraph labels */
            .cluster-label text {
              fill: #cdd6f4 !important;
            }
          `
        );
        
        setSvg(fixedSvg);
      } catch (err) {
        console.error('Mermaid rendering error:', err);
        setError(err instanceof Error ? err.message : 'Failed to render diagram');
      }
    };

    renderDiagram();
  }, [chart]);

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
      <div className="relative" style={{ minHeight: '500px' }}>
        <TransformWrapper
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