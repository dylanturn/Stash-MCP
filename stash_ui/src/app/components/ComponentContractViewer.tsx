import React, { useState, useEffect } from 'react';
import { ChevronDown, ChevronRight, Package, Settings, Eye, Accessibility, TestTube, Palette, Copy, Check } from 'lucide-react';

interface ComponentContractViewerProps {
  content: string;
  onSectionsChange?: (sections: Array<{ id: string; title: string; color?: string }>) => void;
  onActiveSectionChange?: (id: string | null) => void;
}

export function ComponentContractViewer({ content, onSectionsChange, onActiveSectionChange }: ComponentContractViewerProps) {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(['contract', 'interface-props', 'behavior-states', 'accessibility', 'styling'])
  );
  const [copiedItem, setCopiedItem] = useState<string | null>(null);
  const [contract, setContract] = useState<any>(null);

  // Parse contract
  useEffect(() => {
    try {
      const parsed = JSON.parse(content);
      setContract(parsed);
    } catch (e) {
      console.error('Failed to parse component contract:', e);
    }
  }, [content]);

  // Notify parent of available sections when contract changes
  useEffect(() => {
    if (!contract || !onSectionsChange) return;

    const sections: Array<{ id: string; title: string; color?: string }> = [];

    // Add contract info section
    if (contract.component) {
      sections.push({ id: 'contract', title: 'Contract', color: 'var(--stash-accent)' });
    }

    // Add interface section
    if (contract.interface?.props || contract.interface?.events || contract.interface?.slots) {
      sections.push({ id: 'interface', title: 'Interface', color: '#89b4fa' });
    }

    // Add behavior section
    if (contract.behavior?.states || contract.behavior?.interactions) {
      sections.push({ id: 'behavior', title: 'Behavior', color: '#a6e3a1' });
    }

    // Add accessibility section
    if (contract.accessibility) {
      sections.push({ id: 'accessibility', title: 'Accessibility', color: '#f9e2af' });
    }

    // Add styling section
    if (contract.styling) {
      sections.push({ id: 'styling', title: 'Styling', color: '#cba6f7' });
    }

    // Add testing section
    if (contract.testing) {
      sections.push({ id: 'testing', title: 'Testing', color: '#fab387' });
    }

    onSectionsChange(sections);
  }, [contract, onSectionsChange]);

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      return next;
    });
  };

  const copyToClipboard = (text: string, itemId: string) => {
    // Fallback method for clipboard API
    try {
      // Try modern Clipboard API first
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          setCopiedItem(itemId);
          setTimeout(() => setCopiedItem(null), 2000);
        }).catch(() => {
          // Fallback if clipboard API fails
          fallbackCopy(text, itemId);
        });
      } else {
        // Use fallback if Clipboard API not available
        fallbackCopy(text, itemId);
      }
    } catch (err) {
      fallbackCopy(text, itemId);
    }
  };

  const fallbackCopy = (text: string, itemId: string) => {
    // Create a temporary textarea
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

  const renderPropType = (prop: any) => {
    const parts: string[] = [];
    
    if (prop.type) {
      parts.push(prop.type);
    }
    
    if (prop.enum) {
      parts.push(`(${prop.enum.map((v: string) => `"${v}"`).join(' | ')})`);
    }
    
    if (prop.signature) {
      parts.push(prop.signature);
    }
    
    return parts.join(' ');
  };

  const renderPropsTable = (props: any) => {
    const propEntries = Object.entries(props || {});
    if (propEntries.length === 0) return null;

    return (
      <div className="overflow-x-auto">
        <table className="w-full" style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--stash-border)' }}>
              <th className="text-left p-3" style={{ color: 'var(--stash-text-bright)', minWidth: '150px' }}>
                Name
              </th>
              <th className="text-left p-3" style={{ color: 'var(--stash-text-bright)', minWidth: '200px' }}>
                Type
              </th>
              <th className="text-left p-3" style={{ color: 'var(--stash-text-bright)', minWidth: '100px' }}>
                Default
              </th>
              <th className="text-left p-3" style={{ color: 'var(--stash-text-bright)', minWidth: '80px' }}>
                Required
              </th>
              <th className="text-left p-3" style={{ color: 'var(--stash-text-bright)' }}>
                Description
              </th>
            </tr>
          </thead>
          <tbody>
            {propEntries.map(([name, prop]: [string, any]) => (
              <tr
                key={name}
                style={{ borderBottom: '1px solid var(--stash-border)' }}
              >
                <td className="p-3">
                  <code
                    className="px-2 py-1 rounded text-sm"
                    style={{
                      backgroundColor: 'var(--stash-bg-code)',
                      color: 'var(--stash-accent)',
                      fontFamily: 'monospace'
                    }}
                  >
                    {name}
                  </code>
                </td>
                <td className="p-3">
                  <code
                    className="text-sm"
                    style={{ color: 'var(--stash-text-secondary)', fontFamily: 'monospace' }}
                  >
                    {renderPropType(prop)}
                  </code>
                </td>
                <td className="p-3">
                  {prop.default !== undefined ? (
                    <code
                      className="text-sm"
                      style={{ color: 'var(--stash-text-secondary)', fontFamily: 'monospace' }}
                    >
                      {typeof prop.default === 'string' ? `"${prop.default}"` : String(prop.default)}
                    </code>
                  ) : (
                    <span style={{ color: 'var(--stash-text-muted)' }}>—</span>
                  )}
                </td>
                <td className="p-3">
                  {prop.required ? (
                    <span
                      className="px-2 py-0.5 rounded text-xs"
                      style={{ backgroundColor: 'rgba(239, 68, 68, 0.15)', color: '#f87171' }}
                    >
                      Yes
                    </span>
                  ) : (
                    <span style={{ color: 'var(--stash-text-muted)' }}>No</span>
                  )}
                </td>
                <td className="p-3" style={{ color: 'var(--stash-text-primary)' }}>
                  {prop.description || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderEvents = (events: any) => {
    const eventEntries = Object.entries(events || {});
    if (eventEntries.length === 0) return null;

    return (
      <div className="space-y-3">
        {eventEntries.map(([name, event]: [string, any]) => (
          <div
            key={name}
            className="p-4 rounded-lg"
            style={{ backgroundColor: 'var(--stash-bg-surface)', border: '1px solid var(--stash-border)' }}
          >
            <div className="flex items-start gap-3">
              <code
                className="px-2 py-1 rounded text-sm"
                style={{
                  backgroundColor: 'var(--stash-bg-code)',
                  color: 'var(--stash-accent)',
                  fontFamily: 'monospace'
                }}
              >
                {name}
              </code>
              <div className="flex-1">
                <p style={{ color: 'var(--stash-text-primary)', marginBottom: '0.5rem' }}>
                  {event.description}
                </p>
                {event.payload && (
                  <div className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
                    Payload: <code style={{ fontFamily: 'monospace' }}>{JSON.stringify(event.payload)}</code>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  };

  const renderSlots = (slots: any) => {
    const slotEntries = Object.entries(slots || {});
    if (slotEntries.length === 0) return null;

    return (
      <div className="space-y-2">
        {slotEntries.map(([name, slot]: [string, any]) => (
          <div key={name} className="flex items-start gap-3 p-3 rounded" style={{ backgroundColor: 'var(--stash-bg-surface)' }}>
            <code
              className="px-2 py-1 rounded text-sm"
              style={{
                backgroundColor: 'var(--stash-bg-code)',
                color: 'var(--stash-accent)',
                fontFamily: 'monospace'
              }}
            >
              {name}
            </code>
            <p style={{ color: 'var(--stash-text-primary)' }}>{slot.description}</p>
          </div>
        ))}
      </div>
    );
  };

  const renderStates = (states: any) => {
    const stateEntries = Object.entries(states || {});
    if (stateEntries.length === 0) return null;

    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {stateEntries.map(([name, state]: [string, any]) => (
          <div
            key={name}
            className="p-4 rounded-lg"
            style={{ backgroundColor: 'var(--stash-bg-surface)', border: '1px solid var(--stash-border)' }}
          >
            <div className="flex items-center gap-2 mb-2">
              <span
                className="px-2 py-1 rounded text-xs font-mono"
                style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)' }}
              >
                {name}
              </span>
            </div>
            <p className="text-sm mb-2" style={{ color: 'var(--stash-text-primary)' }}>
              {state.description}
            </p>
            {state.triggers && state.triggers.length > 0 && (
              <div className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
                Triggers: {state.triggers.join(', ')}
              </div>
            )}
            {state.conditions && state.conditions.length > 0 && (
              <div className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
                Conditions: {state.conditions.join(', ')}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  };

  const renderInteractions = (interactions: any) => {
    const interactionEntries = Object.entries(interactions || {});
    if (interactionEntries.length === 0) return null;

    return (
      <div className="space-y-3">
        {interactionEntries.map(([name, interaction]: [string, any]) => (
          <div
            key={name}
            className="p-4 rounded-lg"
            style={{ backgroundColor: 'var(--stash-bg-surface)', border: '1px solid var(--stash-border)' }}
          >
            <div className="flex items-start gap-3">
              <code
                className="px-2 py-1 rounded text-sm"
                style={{
                  backgroundColor: 'var(--stash-bg-code)',
                  color: 'var(--stash-accent)',
                  fontFamily: 'monospace'
                }}
              >
                {name}
              </code>
              <div className="flex-1">
                <p className="mb-2" style={{ color: 'var(--stash-text-primary)' }}>
                  {interaction.description}
                </p>
                {interaction.keys && (
                  <div className="text-sm mb-1" style={{ color: 'var(--stash-text-secondary)' }}>
                    Keys: {interaction.keys.map((k: string) => (
                      <kbd key={k} className="px-1.5 py-0.5 mx-1 rounded text-xs" style={{ backgroundColor: 'var(--stash-bg-code)' }}>
                        {k}
                      </kbd>
                    ))}
                  </div>
                )}
                {interaction.conditions && (
                  <div className="text-sm mb-1" style={{ color: 'var(--stash-text-secondary)' }}>
                    Conditions: {interaction.conditions.join(', ')}
                  </div>
                )}
                {interaction.actions && (
                  <div className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
                    Actions: {interaction.actions.join(', ')}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  };

  const renderAccessibility = (accessibility: any) => {
    if (!accessibility) return null;

    return (
      <div className="space-y-4">
        {accessibility.required && (
          <div>
            <h4 className="text-sm mb-3" style={{ color: 'var(--stash-text-bright)' }}>
              Required
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {Object.entries(accessibility.required).map(([key, value]: [string, any]) => (
                <div
                  key={key}
                  className="p-3 rounded"
                  style={{ backgroundColor: 'var(--stash-bg-surface)' }}
                >
                  <code className="text-sm" style={{ color: 'var(--stash-accent)', fontFamily: 'monospace' }}>
                    {key}
                  </code>
                  <span style={{ color: 'var(--stash-text-secondary)' }}> = </span>
                  <span className="text-sm" style={{ color: 'var(--stash-text-primary)' }}>
                    {typeof value === 'string' ? value : JSON.stringify(value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {accessibility.recommended && (
          <div>
            <h4 className="text-sm mb-3" style={{ color: 'var(--stash-text-bright)' }}>
              Recommended
            </h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {Object.entries(accessibility.recommended).map(([key, value]: [string, any]) => (
                <div
                  key={key}
                  className="p-3 rounded"
                  style={{ backgroundColor: 'var(--stash-bg-surface)' }}
                >
                  <code className="text-sm" style={{ color: 'var(--stash-accent)', fontFamily: 'monospace' }}>
                    {key}
                  </code>
                  <span style={{ color: 'var(--stash-text-secondary)' }}> — </span>
                  <span className="text-sm" style={{ color: 'var(--stash-text-primary)' }}>
                    {value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {accessibility.keyboardSupport && (
          <div>
            <h4 className="text-sm mb-3" style={{ color: 'var(--stash-text-bright)' }}>
              Keyboard Support
            </h4>
            <div className="space-y-2">
              {Object.entries(accessibility.keyboardSupport).map(([key, description]: [string, any]) => (
                <div
                  key={key}
                  className="flex items-center gap-3 p-3 rounded"
                  style={{ backgroundColor: 'var(--stash-bg-surface)' }}
                >
                  <kbd
                    className="px-3 py-1.5 rounded text-sm font-mono"
                    style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)' }}
                  >
                    {key}
                  </kbd>
                  <span style={{ color: 'var(--stash-text-primary)' }}>{description}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderStyling = (styling: any) => {
    if (!styling) return null;

    return (
      <div className="space-y-4">
        {styling.variants && (
          <div>
            <h4 className="text-sm mb-3" style={{ color: 'var(--stash-text-bright)' }}>
              Variants
            </h4>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {Object.entries(styling.variants).map(([name, variant]: [string, any]) => (
                <div
                  key={name}
                  className="p-4 rounded-lg"
                  style={{ backgroundColor: 'var(--stash-bg-surface)', border: '1px solid var(--stash-border)' }}
                >
                  <div className="mb-3">
                    <span
                      className="px-2 py-1 rounded text-sm font-mono"
                      style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)' }}
                    >
                      {name}
                    </span>
                  </div>
                  <div className="space-y-1 text-sm">
                    {Object.entries(variant).map(([prop, value]: [string, any]) => (
                      <div key={prop} style={{ color: 'var(--stash-text-secondary)' }}>
                        <span style={{ color: 'var(--stash-text-primary)' }}>{prop}:</span>{' '}
                        <code style={{ fontFamily: 'monospace' }}>
                          {typeof value === 'object' ? JSON.stringify(value) : value}
                        </code>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {styling.sizes && (
          <div>
            <h4 className="text-sm mb-3" style={{ color: 'var(--stash-text-bright)' }}>
              Sizes
            </h4>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
              {Object.entries(styling.sizes).map(([name, size]: [string, any]) => (
                <div
                  key={name}
                  className="p-4 rounded-lg"
                  style={{ backgroundColor: 'var(--stash-bg-surface)', border: '1px solid var(--stash-border)' }}
                >
                  <div className="mb-3">
                    <span
                      className="px-2 py-1 rounded text-sm font-mono"
                      style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)' }}
                    >
                      {name}
                    </span>
                  </div>
                  <div className="space-y-1 text-sm">
                    {Object.entries(size).map(([prop, value]: [string, any]) => (
                      <div key={prop} style={{ color: 'var(--stash-text-secondary)' }}>
                        <span style={{ color: 'var(--stash-text-primary)' }}>{prop}:</span>{' '}
                        <code style={{ fontFamily: 'monospace' }}>{value}</code>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {styling.tokens && styling.tokens.length > 0 && (
          <div>
            <h4 className="text-sm mb-3" style={{ color: 'var(--stash-text-bright)' }}>
              Design Tokens Used
            </h4>
            <div className="flex flex-wrap gap-2">
              {styling.tokens.map((token: string) => (
                <code
                  key={token}
                  className="px-3 py-1.5 rounded text-sm"
                  style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)', fontFamily: 'monospace' }}
                >
                  {token}
                </code>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderTestScenarios = (testing: any) => {
    if (!testing?.scenarios) return null;

    return (
      <div className="space-y-3">
        {testing.scenarios.map((scenario: any, index: number) => (
          <div
            key={index}
            className="p-4 rounded-lg"
            style={{ backgroundColor: 'var(--stash-bg-surface)', border: '1px solid var(--stash-border)' }}
          >
            <h4 className="mb-3" style={{ color: 'var(--stash-text-bright)' }}>
              {scenario.name}
            </h4>
            <ol className="space-y-2 pl-5" style={{ listStyleType: 'decimal' }}>
              {scenario.steps.map((step: string, stepIndex: number) => (
                <li key={stepIndex} style={{ color: 'var(--stash-text-primary)' }}>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    );
  };

  const Section = ({
    id,
    icon: Icon,
    title,
    children,
    defaultExpanded = true
  }: {
    id: string;
    icon: any;
    title: string;
    children: React.ReactNode;
    defaultExpanded?: boolean;
  }) => {
    const isExpanded = expandedSections.has(id);

    return (
      <div className="mb-6">
        <button
          onClick={() => toggleSection(id)}
          className="flex items-center gap-3 w-full p-4 rounded-lg transition-all duration-150 mb-3"
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
          {isExpanded ? (
            <ChevronDown className="w-5 h-5" style={{ color: 'var(--stash-text-secondary)' }} />
          ) : (
            <ChevronRight className="w-5 h-5" style={{ color: 'var(--stash-text-secondary)' }} />
          )}
          <Icon className="w-5 h-5" style={{ color: 'var(--stash-accent)' }} />
          <span className="text-lg" style={{ color: 'var(--stash-text-bright)' }}>
            {title}
          </span>
        </button>
        {isExpanded && <div className="px-4">{children}</div>}
      </div>
    );
  };

  // Show loading state while contract is being parsed
  if (!contract) {
    return (
      <div className="h-full overflow-y-auto flex items-center justify-center" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <p style={{ color: 'var(--stash-text-secondary)' }}>Loading contract...</p>
      </div>
    );
  }

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
              <Package className="w-8 h-8" style={{ color: 'var(--stash-accent)' }} />
            </div>
            <div>
              <h1 className="text-3xl mb-1" style={{ color: 'var(--stash-text-bright)' }}>
                {contract.contract?.name}
              </h1>
              <div className="flex items-center gap-3">
                <span
                  className="px-3 py-1 rounded text-sm font-mono"
                  style={{ backgroundColor: 'var(--stash-bg-code)', color: 'var(--stash-accent)' }}
                >
                  v{contract.contract?.version}
                </span>
                {contract.contract?.category && (
                  <span
                    className="px-3 py-1 rounded text-sm"
                    style={{ backgroundColor: 'var(--stash-bg-surface)', color: 'var(--stash-text-secondary)' }}
                  >
                    {contract.contract.category}
                  </span>
                )}
              </div>
            </div>
          </div>
          {contract.contract?.description && (
            <p className="text-lg" style={{ color: 'var(--stash-text-primary)' }}>
              {contract.contract.description}
            </p>
          )}
        </div>

        {/* Interface Section */}
        {contract.interface && (
          <Section id="interface-props" icon={Settings} title="Interface">
            {contract.interface.props && (
              <div className="mb-6">
                <h3 className="text-base mb-3" style={{ color: 'var(--stash-text-bright)' }}>
                  Props
                </h3>
                {renderPropsTable(contract.interface.props)}
              </div>
            )}
            {contract.interface.events && (
              <div className="mb-6">
                <h3 className="text-base mb-3" style={{ color: 'var(--stash-text-bright)' }}>
                  Events
                </h3>
                {renderEvents(contract.interface.events)}
              </div>
            )}
            {contract.interface.slots && (
              <div>
                <h3 className="text-base mb-3" style={{ color: 'var(--stash-text-bright)' }}>
                  Slots
                </h3>
                {renderSlots(contract.interface.slots)}
              </div>
            )}
          </Section>
        )}

        {/* Behavior Section */}
        {contract.behavior && (
          <Section id="behavior-states" icon={Eye} title="Behavior">
            {contract.behavior.states && (
              <div className="mb-6">
                <h3 className="text-base mb-3" style={{ color: 'var(--stash-text-bright)' }}>
                  States
                </h3>
                {renderStates(contract.behavior.states)}
              </div>
            )}
            {contract.behavior.interactions && (
              <div>
                <h3 className="text-base mb-3" style={{ color: 'var(--stash-text-bright)' }}>
                  Interactions
                </h3>
                {renderInteractions(contract.behavior.interactions)}
              </div>
            )}
          </Section>
        )}

        {/* Accessibility Section */}
        {contract.accessibility && (
          <Section id="accessibility" icon={Accessibility} title="Accessibility">
            {renderAccessibility(contract.accessibility)}
          </Section>
        )}

        {/* Styling Section */}
        {contract.styling && (
          <Section id="styling" icon={Palette} title="Styling">
            {renderStyling(contract.styling)}
          </Section>
        )}

        {/* Testing Section */}
        {contract.testing && (
          <Section id="testing" icon={TestTube} title="Testing">
            {renderTestScenarios(contract.testing)}
          </Section>
        )}
      </div>
    </div>
  );
}