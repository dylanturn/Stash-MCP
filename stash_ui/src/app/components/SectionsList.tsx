import React from 'react';
import { List } from 'lucide-react';

export interface Section {
  id: string;
  title: string;
  icon?: string;
  color?: string;
}

interface SectionsListProps {
  sections: Section[];
  activeId: string | null;
  onSectionClick: (id: string) => void;
  title?: string;
}

export function SectionsList({ sections, activeId, onSectionClick, title = 'Sections' }: SectionsListProps) {
  if (sections.length === 0) {
    return null;
  }

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <List className="w-4 h-4" style={{ color: 'var(--stash-text-bright)' }} />
        <h3 className="text-sm" style={{ color: 'var(--stash-text-bright)' }}>
          {title}
        </h3>
      </div>

      <nav className="space-y-1">
        {sections.map((section) => {
          const isActive = section.id === activeId;

          return (
            <button
              key={section.id}
              onClick={() => onSectionClick(section.id)}
              className="w-full text-left text-sm py-2 px-3 rounded transition-all duration-150"
              style={{
                color: isActive ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
                backgroundColor: isActive ? 'var(--stash-bg-hover)' : 'transparent',
                borderLeft: isActive ? `3px solid ${section.color || 'var(--stash-accent)'}` : '3px solid transparent',
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
              {section.title}
            </button>
          );
        })}
      </nav>
    </div>
  );
}
