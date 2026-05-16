import React, { useState, useEffect, useRef } from 'react';
import { GitBranch, Play, ChevronDown, ChevronRight, CheckCircle2, AlertCircle, Workflow, Settings, FileText } from 'lucide-react';
import yaml from 'js-yaml';

interface ArazzoViewerProps {
  content: string;
  onSectionsChange?: (sections: Array<{ id: string; title: string; color?: string }>) => void;
  onActiveSectionChange?: (id: string | null) => void;
}

export function ArazzoViewer({ content, onSectionsChange, onActiveSectionChange }: ArazzoViewerProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());
  const [expandedWorkflows, setExpandedWorkflows] = useState<Set<string>>(new Set(['0'])); // First workflow expanded by default
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const sectionRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  // Notify parent of available sections when spec changes
  useEffect(() => {
    if (!onSectionsChange) return;

    let spec: any;
    try {
      spec = yaml.load(content) as any;
    } catch (e) {
      return;
    }

    if (!spec) return;

    const sections = [];
    
    // Add info section
    if (spec.info) {
      sections.push({ id: 'info', title: 'Info', color: 'var(--stash-accent)' });
    }
    
    // Add source APIs section
    if (spec.sourceDescriptions && spec.sourceDescriptions.length > 0) {
      sections.push({ id: 'source-apis', title: 'Source APIs', color: '#89b4fa' });
    }
    
    // Add workflow sections
    if (spec.workflows && Array.isArray(spec.workflows)) {
      spec.workflows.forEach((workflow: any, index: number) => {
        sections.push({
          id: `workflow-${index}`,
          title: workflow.workflowId || workflow.summary || `Workflow ${index + 1}`,
          color: '#a6e3a1'
        });
      });
    }

    onSectionsChange(sections);
  }, [content, onSectionsChange]);

  const toggleStep = (workflowIndex: number, stepId: string) => {
    const key = `${workflowIndex}-${stepId}`;
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const toggleWorkflow = (index: string) => {
    setExpandedWorkflows((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  // Set up intersection observer for scrollspy
  useEffect(() => {
    if (!onActiveSectionChange) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visibleSections = entries
          .filter(entry => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);

        if (visibleSections.length > 0) {
          const firstVisible = visibleSections[0].target.getAttribute('data-section-id');
          if (firstVisible) {
            setActiveSection(firstVisible);
            onActiveSectionChange?.(firstVisible);
          }
        }
      },
      {
        root: null,
        rootMargin: '-100px 0px -60% 0px',
        threshold: [0, 0.25, 0.5, 0.75, 1]
      }
    );

    const timeoutId = setTimeout(() => {
      sectionRefs.current.forEach((element) => {
        if (element) observer.observe(element);
      });
    }, 100);

    return () => {
      clearTimeout(timeoutId);
      observer.disconnect();
    };
  }, [onActiveSectionChange]);

  // Parse spec for rendering
  let spec: any;
  try {
    spec = yaml.load(content) as any;
  } catch (e) {
    return (
      <div className="p-8" style={{ color: 'var(--stash-text-secondary)' }}>
        <p>Error parsing Arazzo YAML</p>
      </div>
    );
  }

  const renderValue = (value: any): string => {
    if (typeof value === 'string') return value;
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
    if (typeof value === 'object') return JSON.stringify(value, null, 2);
    return String(value);
  };

  const renderParameters = (parameters: any[]) => {
    if (!parameters || parameters.length === 0) return null;

    return (
      <div className="mt-3">
        <h5 className="text-xs mb-2" style={{ color: 'var(--stash-text-bright)' }}>
          Parameters
        </h5>
        <div className="space-y-2">
          {parameters.map((param: any, index: number) => (
            <div
              key={index}
              className="p-3 rounded text-sm"
              style={{ backgroundColor: 'var(--stash-bg-base)', border: '1px solid var(--stash-border)' }}
            >
              <div className="flex items-start gap-2 mb-1">
                <code className="text-xs" style={{ color: 'var(--stash-accent)', fontFamily: 'monospace' }}>
                  {param.name}
                </code>
                {param.in && (
                  <span className="text-xs px-2 py-0.5 rounded" style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-text-secondary)' }}>
                    {param.in}
                  </span>
                )}
              </div>
              <div className="text-xs" style={{ color: 'var(--stash-text-secondary)', fontFamily: 'monospace' }}>
                {renderValue(param.value)}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderRequestBody = (requestBody: any) => {
    if (!requestBody) return null;

    return (
      <div className="mt-3">
        <h5 className="text-xs mb-2" style={{ color: 'var(--stash-text-bright)' }}>
          Request Body
        </h5>
        <div
          className="p-3 rounded text-sm"
          style={{ backgroundColor: 'var(--stash-bg-base)', border: '1px solid var(--stash-border)' }}
        >
          {requestBody.contentType && (
            <div className="mb-2 text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
              Content-Type: <code style={{ fontFamily: 'monospace' }}>{requestBody.contentType}</code>
            </div>
          )}
          <pre
            className="text-xs overflow-x-auto"
            style={{ color: 'var(--stash-text-primary)', fontFamily: 'monospace' }}
          >
            {renderValue(requestBody.payload)}
          </pre>
        </div>
      </div>
    );
  };

  const renderSuccessCriteria = (criteria: any[]) => {
    if (!criteria || criteria.length === 0) return null;

    return (
      <div className="mt-3">
        <h5 className="text-xs mb-2" style={{ color: 'var(--stash-text-bright)' }}>
          Success Criteria
        </h5>
        <div className="space-y-1">
          {criteria.map((criterion: any, index: number) => (
            <div key={index} className="flex items-start gap-2 text-sm">
              <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: '#86efac' }} />
              <code style={{ color: 'var(--stash-text-primary)', fontFamily: 'monospace', fontSize: '0.75rem' }}>
                {criterion.condition || criterion.context || renderValue(criterion)}
              </code>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderOutputs = (outputs: any) => {
    if (!outputs) return null;

    const outputEntries = Object.entries(outputs);
    if (outputEntries.length === 0) return null;

    return (
      <div className="mt-3">
        <h5 className="text-xs mb-2" style={{ color: 'var(--stash-text-bright)' }}>
          Outputs
        </h5>
        <div className="space-y-1">
          {outputEntries.map(([key, value]: [string, any]) => (
            <div
              key={key}
              className="p-2 rounded text-xs"
              style={{ backgroundColor: 'var(--stash-bg-base)' }}
            >
              <code style={{ color: 'var(--stash-accent)', fontFamily: 'monospace' }}>
                {key}
              </code>
              <span style={{ color: 'var(--stash-text-secondary)' }}> = </span>
              <code style={{ color: 'var(--stash-text-secondary)', fontFamily: 'monospace' }}>
                {renderValue(value)}
              </code>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderStep = (step: any, stepIndex: number, workflowIndex: number, totalSteps: number) => {
    const stepKey = `${workflowIndex}-${step.stepId}`;
    const isExpanded = expandedSteps.has(stepKey);
    const isLastStep = stepIndex === totalSteps - 1;

    return (
      <div key={step.stepId} className="relative">
        {/* Connector Line */}
        {!isLastStep && (
          <div
            className="absolute left-6 top-12 w-0.5 h-full"
            style={{ backgroundColor: 'var(--stash-border)' }}
          />
        )}

        <div className="flex gap-4">
          {/* Step Number */}
          <div className="flex flex-col items-center flex-shrink-0">
            <div
              className="w-12 h-12 rounded-full flex items-center justify-center text-sm font-mono relative z-10"
              style={{ backgroundColor: 'var(--stash-accent)', color: 'var(--stash-bg-base)' }}
            >
              {stepIndex + 1}
            </div>
          </div>

          {/* Step Content */}
          <div className="flex-1 mb-6">
            <button
              onClick={() => toggleStep(workflowIndex, step.stepId)}
              className="w-full text-left p-4 rounded-lg transition-all duration-150"
              style={{
                backgroundColor: 'var(--stash-bg-surface)',
                border: '1px solid var(--stash-border)'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--stash-bg-surface)';
              }}
            >
              <div className="flex items-start gap-3">
                <div className="flex-shrink-0 mt-1">
                  {isExpanded ? (
                    <ChevronDown className="w-5 h-5" style={{ color: 'var(--stash-text-secondary)' }} />
                  ) : (
                    <ChevronRight className="w-5 h-5" style={{ color: 'var(--stash-text-secondary)' }} />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <code
                      className="px-2 py-1 rounded text-sm font-mono"
                      style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)' }}
                    >
                      {step.stepId}
                    </code>
                    {step.operationId && (
                      <span className="text-xs px-2 py-1 rounded" style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-text-secondary)' }}>
                        {step.operationId}
                      </span>
                    )}
                    {step.dependsOn && (
                      <div className="flex items-center gap-1 text-xs" style={{ color: 'var(--stash-text-muted)' }}>
                        <GitBranch className="w-3 h-3" />
                        depends on: <code style={{ fontFamily: 'monospace' }}>{Array.isArray(step.dependsOn) ? step.dependsOn.join(', ') : step.dependsOn}</code>
                      </div>
                    )}
                  </div>
                  <p style={{ color: 'var(--stash-text-primary)' }}>
                    {step.description || step.summary || 'No description'}
                  </p>
                </div>
              </div>
            </button>

            {/* Expanded Step Details */}
            {isExpanded && (
              <div className="mt-3 p-4 rounded-lg" style={{ backgroundColor: 'var(--stash-bg-base)', border: '1px solid var(--stash-border)' }}>
                {renderParameters(step.parameters)}
                {renderRequestBody(step.requestBody)}
                {renderSuccessCriteria(step.successCriteria)}
                {renderOutputs(step.outputs)}
                
                {step.onSuccess && step.onSuccess.length > 0 && (
                  <div className="mt-3">
                    <h5 className="text-xs mb-2" style={{ color: 'var(--stash-text-bright)' }}>
                      On Success
                    </h5>
                    <div className="space-y-1">
                      {step.onSuccess.map((action: any, index: number) => (
                        <div key={index} className="text-xs p-2 rounded" style={{ backgroundColor: 'var(--stash-bg-surface)', color: 'var(--stash-text-secondary)' }}>
                          {action.type}: {action.workflowId || action.stepId || renderValue(action)}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {step.onFailure && step.onFailure.length > 0 && (
                  <div className="mt-3">
                    <h5 className="text-xs mb-2" style={{ color: 'var(--stash-text-bright)' }}>
                      On Failure
                    </h5>
                    <div className="space-y-1">
                      {step.onFailure.map((action: any, index: number) => (
                        <div key={index} className="text-xs p-2 rounded" style={{ backgroundColor: 'var(--stash-bg-surface)', color: '#f87171' }}>
                          {action.type}: {action.workflowId || action.stepId || renderValue(action)}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  const renderWorkflow = (workflow: any, index: number) => {
    const isExpanded = expandedWorkflows.has(String(index));
    const workflowId = `workflow-${index}`;

    return (
      <div 
        key={workflow.workflowId} 
        className="mb-6 scroll-mt-20"
        ref={(el) => {
          if (el) sectionRefs.current.set(workflowId, el);
        }}
        data-section-id={workflowId}
      >
        <button
          onClick={() => toggleWorkflow(String(index))}
          className="w-full text-left p-5 rounded-lg transition-all duration-150"
          style={{
            backgroundColor: 'var(--stash-bg-surface)',
            border: '2px solid var(--stash-border)'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = 'var(--stash-accent)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = 'var(--stash-border)';
          }}
        >
          <div className="flex items-start gap-4">
            <div className="flex-shrink-0 mt-1">
              {isExpanded ? (
                <ChevronDown className="w-6 h-6" style={{ color: 'var(--stash-accent)' }} />
              ) : (
                <ChevronRight className="w-6 h-6" style={{ color: 'var(--stash-accent)' }} />
              )}
            </div>
            <div
              className="p-3 rounded-lg flex-shrink-0"
              style={{ backgroundColor: 'var(--stash-bg-base)' }}
            >
              <Workflow className="w-6 h-6" style={{ color: 'var(--stash-accent)' }} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3 mb-2">
                <h3 className="text-xl" style={{ color: 'var(--stash-text-bright)' }}>
                  {workflow.summary || workflow.workflowId}
                </h3>
                {workflow.steps && (
                  <span
                    className="px-2 py-1 rounded text-xs"
                    style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-text-secondary)' }}
                  >
                    {workflow.steps.length} steps
                  </span>
                )}
              </div>
              <code
                className="text-sm px-2 py-1 rounded"
                style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)', fontFamily: 'monospace' }}
              >
                {workflow.workflowId}
              </code>
              {workflow.description && (
                <p className="mt-3 whitespace-pre-line" style={{ color: 'var(--stash-text-primary)' }}>
                  {workflow.description}
                </p>
              )}
            </div>
          </div>
        </button>

        {/* Expanded Workflow Details */}
        {isExpanded && (
          <div className="mt-4 p-5 rounded-lg" style={{ backgroundColor: 'var(--stash-bg-surface)' }}>
            {/* Workflow Inputs */}
            {workflow.inputs && (
              <div className="mb-6">
                <h4 className="flex items-center gap-2 mb-3" style={{ color: 'var(--stash-text-bright)' }}>
                  <Settings className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
                  Inputs
                </h4>
                <div
                  className="p-4 rounded-lg"
                  style={{ backgroundColor: 'var(--stash-bg-base)', border: '1px solid var(--stash-border)' }}
                >
                  {workflow.inputs.properties && (
                    <div className="space-y-3">
                      {Object.entries(workflow.inputs.properties).map(([key, prop]: [string, any]) => (
                        <div key={key}>
                          <div className="flex items-start gap-2 mb-1">
                            <code className="text-sm" style={{ color: 'var(--stash-accent)', fontFamily: 'monospace' }}>
                              {key}
                            </code>
                            <span className="text-xs px-2 py-0.5 rounded" style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-text-secondary)' }}>
                              {prop.type}
                            </span>
                          </div>
                          {prop.description && (
                            <p className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
                              {prop.description}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Workflow Steps */}
            {workflow.steps && workflow.steps.length > 0 && (
              <div className="mb-6">
                <h4 className="flex items-center gap-2 mb-4" style={{ color: 'var(--stash-text-bright)' }}>
                  <Play className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
                  Steps
                </h4>
                <div>
                  {workflow.steps.map((step: any, stepIndex: number) =>
                    renderStep(step, stepIndex, index, workflow.steps.length)
                  )}
                </div>
              </div>
            )}

            {/* Workflow Outputs */}
            {workflow.outputs && (
              <div>
                <h4 className="flex items-center gap-2 mb-3" style={{ color: 'var(--stash-text-bright)' }}>
                  <FileText className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
                  Outputs
                </h4>
                <div
                  className="p-4 rounded-lg"
                  style={{ backgroundColor: 'var(--stash-bg-base)', border: '1px solid var(--stash-border)' }}
                >
                  <div className="space-y-2">
                    {Object.entries(workflow.outputs).map(([key, value]: [string, any]) => (
                      <div key={key} className="flex items-start gap-2">
                        <code className="text-sm" style={{ color: 'var(--stash-accent)', fontFamily: 'monospace' }}>
                          {key}
                        </code>
                        <span style={{ color: 'var(--stash-text-secondary)' }}>=</span>
                        <code className="text-sm flex-1" style={{ color: 'var(--stash-text-secondary)', fontFamily: 'monospace' }}>
                          {renderValue(value)}
                        </code>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  useEffect(() => {
    if (onActiveSectionChange) {
      const activeSectionId = expandedWorkflows.size > 0 ? `workflow-${Array.from(expandedWorkflows)[0]}` : null;
      onActiveSectionChange(activeSectionId);
    }
  }, [expandedWorkflows, onActiveSectionChange]);

  return (
    <div className="h-full overflow-y-auto" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
      <div className="max-w-[1200px] mx-auto px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-4">
            <div
              className="p-3 rounded-lg"
              style={{ backgroundColor: 'var(--stash-bg-surface)' }}
            >
              <Workflow className="w-8 h-8" style={{ color: 'var(--stash-accent)' }} />
            </div>
            <div>
              <h1 className="text-3xl mb-1" style={{ color: 'var(--stash-text-bright)' }}>
                {spec.info?.title || 'Arazzo Workflow'}
              </h1>
              <div className="flex items-center gap-3">
                <span
                  className="px-3 py-1 rounded text-sm font-mono"
                  style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)' }}
                >
                  Arazzo {spec.arazzo}
                </span>
                {spec.info?.version && (
                  <span
                    className="px-3 py-1 rounded text-sm"
                    style={{ backgroundColor: 'var(--stash-bg-surface)', color: 'var(--stash-text-secondary)' }}
                  >
                    v{spec.info.version}
                  </span>
                )}
              </div>
            </div>
          </div>
          {spec.info?.description && (
            <p className="text-lg whitespace-pre-line" style={{ color: 'var(--stash-text-primary)' }}>
              {spec.info.description}
            </p>
          )}
        </div>

        {/* Source Descriptions */}
        {spec.sourceDescriptions && spec.sourceDescriptions.length > 0 && (
          <div className="mb-8">
            <h2 className="text-xl mb-4" style={{ color: 'var(--stash-text-bright)' }}>
              Source APIs
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {spec.sourceDescriptions.map((source: any, index: number) => (
                <div
                  key={index}
                  className="p-4 rounded-lg"
                  style={{ backgroundColor: 'var(--stash-bg-surface)', border: '1px solid var(--stash-border)' }}
                >
                  <div className="flex items-center gap-2 mb-2">
                    <code
                      className="px-2 py-1 rounded text-sm font-mono"
                      style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)' }}
                    >
                      {source.name}
                    </code>
                    <span
                      className="px-2 py-1 rounded text-xs"
                      style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-text-secondary)' }}
                    >
                      {source.type}
                    </span>
                  </div>
                  <a
                    href={source.url}
                    className="text-sm break-all"
                    style={{ color: 'var(--stash-accent)', textDecoration: 'underline' }}
                  >
                    {source.url}
                  </a>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Workflows */}
        {spec.workflows && spec.workflows.length > 0 && (
          <div>
            <h2 className="text-xl mb-4" style={{ color: 'var(--stash-text-bright)' }}>
              Workflows
            </h2>
            {spec.workflows.map((workflow: any, index: number) => renderWorkflow(workflow, index))}
          </div>
        )}
      </div>
    </div>
  );
}