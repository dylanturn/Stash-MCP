import React, { useMemo, useState } from 'react';
import { FileNode } from '../types';
import { Folder, FileText, Home, ChevronRight, Move, Trash2 } from 'lucide-react';

interface DirectoryListingProps {
  directory: FileNode;
  onSelectItem: (item: FileNode) => void;
  onMoveItem?: (item: FileNode) => void;
  onDeleteItem?: (item: FileNode) => void;
}

export function DirectoryListing({ directory, onSelectItem, onMoveItem, onDeleteItem }: DirectoryListingProps) {
  // Get breadcrumb path
  const breadcrumbs = useMemo(() => {
    const parts = directory.path.split('/').filter(Boolean);
    return [
      { name: 'Home', path: '/' },
      ...parts.map((part, index) => ({
        name: part,
        path: '/' + parts.slice(0, index + 1).join('/')
      }))
    ];
  }, [directory.path]);

  // Format file size
  const formatSize = (bytes?: number): string => {
    if (!bytes) return '—';
    const kb = bytes / 1024;
    return `${kb.toFixed(1)} KB`;
  };

  // Format date
  const formatDate = (isoString?: string): string => {
    if (!isoString) return '—';
    const date = new Date(isoString);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}`;
  };

  // Get MIME type
  const getType = (node: FileNode): string => {
    if (node.type === 'folder') return 'directory';
    if (node.extension === 'md') return 'text/markdown';
    if (node.extension === 'txt') return 'text/plain';
    if (node.extension === 'json') return 'application/json';
    return 'text/plain';
  };

  // Sort children: directories first, then files, alphabetically
  const sortedChildren = useMemo(() => {
    if (!directory.children) return [];
    return [...directory.children].sort((a, b) => {
      if (a.type === 'folder' && b.type !== 'folder') return -1;
      if (a.type !== 'folder' && b.type === 'folder') return 1;
      return a.name.localeCompare(b.name);
    });
  }, [directory.children]);

  // Track hover state for each row
  const [hoveredRow, setHoveredRow] = useState<string | null>(null);

  const handleMove = (e: React.MouseEvent, item: FileNode) => {
    e.stopPropagation();
    onMoveItem?.(item);
  };

  const handleDelete = (e: React.MouseEvent, item: FileNode) => {
    e.stopPropagation();
    onDeleteItem?.(item);
  };

  return (
    <div className="h-full flex flex-col" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
      {/* Breadcrumb */}
      <div 
        className="flex items-center gap-2 px-8 py-4 border-b"
        style={{ borderColor: 'var(--stash-border)' }}
      >
        {breadcrumbs.map((crumb, index) => (
          <div key={crumb.path} className="flex items-center gap-2">
            {index > 0 && (
              <ChevronRight 
                className="w-4 h-4" 
                style={{ color: 'var(--stash-text-secondary)' }} 
              />
            )}
            {index === 0 ? (
              <div className="flex items-center gap-1.5">
                <Home 
                  className="w-4 h-4" 
                  style={{ color: 'var(--stash-accent)' }} 
                />
                <span 
                  className="text-sm"
                  style={{ color: 'var(--stash-accent)' }}
                >
                  {crumb.name}
                </span>
              </div>
            ) : (
              <span 
                className="text-sm"
                style={{ 
                  color: index === breadcrumbs.length - 1 
                    ? 'var(--stash-text-primary)' 
                    : 'var(--stash-text-secondary)' 
                }}
              >
                {crumb.name}
              </span>
            )}
          </div>
        ))}
      </div>

      {/* Directory Header */}
      <div className="px-8 py-6">
        <h1 
          className="text-2xl"
          style={{ color: 'var(--stash-text-bright)' }}
        >
          {directory.name}
        </h1>
      </div>

      {/* Directory Contents Table */}
      <div className="flex-1 overflow-y-auto px-8 pb-8">
        <table className="w-full">
          <thead>
            <tr 
              className="border-b"
              style={{ borderColor: 'var(--stash-border)' }}
            >
              <th 
                className="text-left py-3 pr-4 text-xs tracking-wide"
                style={{ color: 'var(--stash-text-secondary)' }}
              >
                Name
              </th>
              <th 
                className="text-left py-3 px-4 text-xs tracking-wide"
                style={{ color: 'var(--stash-text-secondary)' }}
              >
                Type
              </th>
              <th 
                className="text-left py-3 px-4 text-xs tracking-wide"
                style={{ color: 'var(--stash-text-secondary)' }}
              >
                Size
              </th>
              <th 
                className="text-left py-3 pl-4 text-xs tracking-wide"
                style={{ color: 'var(--stash-text-secondary)' }}
              >
                Modified
              </th>
              <th 
                className="text-right py-3 pl-4 pr-2 text-xs tracking-wide w-20"
                style={{ color: 'var(--stash-text-secondary)' }}
              >
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedChildren.map((item) => (
              <tr
                key={item.id}
                className="border-b transition-colors duration-150 group"
                style={{ borderColor: 'var(--stash-border)' }}
                onMouseEnter={() => setHoveredRow(item.id)}
                onMouseLeave={() => setHoveredRow(null)}
              >
                {/* Name */}
                <td className="py-3 pr-4" onClick={() => onSelectItem(item)}>
                  <div className="flex items-center gap-2 cursor-pointer">
                    {item.type === 'folder' ? (
                      <Folder 
                        className="w-4 h-4 flex-shrink-0" 
                        style={{ color: 'var(--stash-text-secondary)' }} 
                      />
                    ) : (
                      <FileText 
                        className="w-4 h-4 flex-shrink-0" 
                        style={{ color: 'var(--stash-text-secondary)' }} 
                      />
                    )}
                    <span 
                      className="text-sm truncate"
                      style={{ color: 'var(--stash-accent)' }}
                    >
                      {item.name}
                    </span>
                  </div>
                </td>

                {/* Type */}
                <td 
                  className="py-3 px-4 text-sm cursor-pointer"
                  style={{ color: 'var(--stash-text-secondary)' }}
                  onClick={() => onSelectItem(item)}
                >
                  {getType(item)}
                </td>

                {/* Size */}
                <td 
                  className="py-3 px-4 text-sm cursor-pointer"
                  style={{ color: 'var(--stash-text-secondary)' }}
                  onClick={() => onSelectItem(item)}
                >
                  {item.type === 'folder' ? '—' : formatSize(item.size)}
                </td>

                {/* Modified */}
                <td 
                  className="py-3 pl-4 text-sm cursor-pointer"
                  style={{ color: 'var(--stash-text-secondary)' }}
                  onClick={() => onSelectItem(item)}
                >
                  {item.type === 'folder' ? '—' : formatDate(item.lastModified)}
                </td>

                {/* Actions */}
                <td className="py-3 pl-4 pr-2">
                  <div 
                    className="flex items-center justify-end gap-1 transition-opacity duration-150"
                    style={{ opacity: hoveredRow === item.id ? 1 : 0 }}
                  >
                    <button
                      onClick={(e) => handleMove(e, item)}
                      className="p-1.5 rounded transition-colors duration-150"
                      style={{ color: 'var(--stash-text-secondary)' }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--stash-bg-surface)';
                        e.currentTarget.style.color = 'var(--stash-text-primary)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'transparent';
                        e.currentTarget.style.color = 'var(--stash-text-secondary)';
                      }}
                      title="Move"
                    >
                      <Move className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={(e) => handleDelete(e, item)}
                      className="p-1.5 rounded transition-colors duration-150"
                      style={{ color: 'var(--stash-text-secondary)' }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--stash-bg-surface)';
                        e.currentTarget.style.color = '#f38ba8';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'transparent';
                        e.currentTarget.style.color = 'var(--stash-text-secondary)';
                      }}
                      title="Delete"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* Empty state */}
        {sortedChildren.length === 0 && (
          <div className="flex items-center justify-center py-16">
            <p style={{ color: 'var(--stash-text-secondary)' }}>
              This directory is empty
            </p>
          </div>
        )}
      </div>
    </div>
  );
}