import React, { useState, useEffect } from 'react';
import { ChevronDown } from 'lucide-react';

interface AccordionProps {
  title: string;
  children: React.ReactNode;
  defaultExpanded?: boolean;
  isExpanded?: boolean;
  onToggle?: (expanded: boolean) => void;
}

export function Accordion({ 
  title, 
  children, 
  defaultExpanded = true,
  isExpanded: controlledExpanded,
  onToggle
}: AccordionProps) {
  const [internalExpanded, setInternalExpanded] = useState(defaultExpanded);
  
  // Use controlled state if provided, otherwise use internal state
  const isExpanded = controlledExpanded !== undefined ? controlledExpanded : internalExpanded;

  // Update internal state when defaultExpanded changes
  useEffect(() => {
    if (controlledExpanded === undefined) {
      setInternalExpanded(defaultExpanded);
    }
  }, [defaultExpanded, controlledExpanded]);

  const handleToggle = () => {
    const newExpanded = !isExpanded;
    if (onToggle) {
      onToggle(newExpanded);
    } else {
      setInternalExpanded(newExpanded);
    }
  };

  return (
    <div>
      {/* Accordion Header */}
      <button
        onClick={handleToggle}
        className="w-full flex items-center justify-between py-3 transition-all duration-150"
        style={{
          color: 'var(--stash-text-bright)',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.opacity = '0.8';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.opacity = '1';
        }}
      >
        <h3 className="text-sm font-medium">
          {title}
        </h3>
        <ChevronDown
          className="w-4 h-4 transition-transform duration-150"
          style={{
            color: 'var(--stash-text-secondary)',
            transform: isExpanded ? 'rotate(0deg)' : 'rotate(-90deg)',
          }}
        />
      </button>

      {/* Accordion Content */}
      <div
        className="overflow-hidden transition-all duration-150"
        style={{
          maxHeight: isExpanded ? '2000px' : '0',
          opacity: isExpanded ? 1 : 0,
        }}
      >
        <div className="pb-4">
          {children}
        </div>
      </div>
    </div>
  );
}
