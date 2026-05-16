import React from 'react';
import { List } from 'lucide-react';

export interface Endpoint {
  id: string;
  method: string;
  path: string;
  summary?: string;
}

interface EndpointsListProps {
  endpoints: Endpoint[];
  activeId: string | null;
  onEndpointClick: (id: string) => void;
}

export function EndpointsList({ endpoints, activeId, onEndpointClick }: EndpointsListProps) {
  if (endpoints.length === 0) {
    return null;
  }

  const getMethodColor = (method: string) => {
    const colors: { [key: string]: string } = {
      get: '#94e2d5',
      post: '#a6e3a1',
      put: '#f9e2af',
      patch: '#cba6f7',
      delete: '#f38ba8',
    };
    return colors[method.toLowerCase()] || colors.get;
  };

  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <List className="w-4 h-4" style={{ color: 'var(--stash-text-bright)' }} />
        <h3 className="text-sm" style={{ color: 'var(--stash-text-bright)' }}>
          Endpoints
        </h3>
      </div>

      <nav className="space-y-1">
        {endpoints.map((endpoint) => {
          const isActive = endpoint.id === activeId;
          const methodColor = getMethodColor(endpoint.method);

          return (
            <button
              key={endpoint.id}
              onClick={() => onEndpointClick(endpoint.id)}
              className="w-full text-left text-sm py-2 px-2 rounded transition-all duration-150 flex items-center gap-2"
              style={{
                color: isActive ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)',
                backgroundColor: isActive ? 'var(--stash-bg-hover)' : 'transparent',
                borderLeft: isActive ? `2px solid ${methodColor}` : '2px solid transparent',
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
              <span 
                className="px-2 py-0.5 rounded text-xs font-bold uppercase flex-shrink-0"
                style={{ 
                  backgroundColor: methodColor,
                  color: 'var(--stash-bg-base)',
                  minWidth: '50px',
                  textAlign: 'center'
                }}
              >
                {endpoint.method}
              </span>
              <code 
                className="font-mono text-xs flex-1 truncate"
                style={{ 
                  color: isActive ? 'var(--stash-text-bright)' : 'var(--stash-text-secondary)'
                }}
              >
                {endpoint.path}
              </code>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
