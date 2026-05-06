import React from 'react';
import { List } from 'lucide-react';

export interface Heading {
  id: string;
  text: string;
  level: number;
}

interface TableOfContentsProps {
  headings: Heading[];
  activeId: string | null;
  onHeadingClick: (id: string) => void;
}

export function TableOfContents({ headings, activeId, onHeadingClick }: TableOfContentsProps) {
  if (headings.length === 0) {
    return null;
  }

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <List className="w-4 h-4" style={{ color: 'var(--stash-text-bright)' }} />
        <h3 className="text-sm" style={{ color: 'var(--stash-text-bright)' }}>
          On This Page
        </h3>
      </div>

      <nav className="space-y-1">
        {headings.map((heading) => {
          const isActive = heading.id === activeId;
          const indent = (heading.level - 1) * 12;

          return (
            <button
              key={heading.id}
              onClick={() => onHeadingClick(heading.id)}
              className="w-full text-left text-sm py-1.5 px-2 rounded transition-all duration-150"
              style={{
                paddingLeft: `${indent + 8}px`,
                color: isActive ? 'var(--stash-accent)' : 'var(--stash-text-secondary)',
                backgroundColor: isActive ? 'rgba(148, 226, 213, 0.1)' : 'transparent',
                borderLeft: isActive ? '2px solid var(--stash-accent)' : '2px solid transparent',
              }}
              onMouseEnter={(e) => {
                if (!isActive) {
                  e.currentTarget.style.color = 'var(--stash-text-primary)';
                  e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                }
              }}
              onMouseLeave={(e) => {
                if (!isActive) {
                  e.currentTarget.style.color = 'var(--stash-text-secondary)';
                  e.currentTarget.style.backgroundColor = 'transparent';
                }
              }}
            >
              {heading.text}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
