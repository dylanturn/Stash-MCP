import React, { useState } from 'react';
import { FileNode } from '../types';
import { ChevronRight, ChevronDown, FileText, Folder, FolderOpen, Search, Plus, GitBranch } from 'lucide-react';
import { UserBadge } from './UserBadge';
import { GitBranchInfo } from '../mockData/gitChanges';

interface FileTreeProps {
  tree: FileNode[];
  selectedFile: FileNode | null;
  onSelectFile: (file: FileNode) => void;
  onClearSelection?: () => void;
  onNewDocument: () => void;
  onOpenSettings?: () => void;
  onMoveItem?: (item: FileNode) => void;
  onDeleteItem?: (item: FileNode) => void;
  gitInfo?: GitBranchInfo;
}

interface FileTreeItemProps {
  node: FileNode;
  level: number;
  selectedFile: FileNode | null;
  onSelectFile: (file: FileNode) => void;
  onMoveItem?: (item: FileNode) => void;
  onDeleteItem?: (item: FileNode) => void;
}

function FileTreeItem({ node, level, selectedFile, onSelectFile, onMoveItem, onDeleteItem }: FileTreeItemProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const isSelected = selectedFile?.id === node.id;

  const getFileIcon = (extension?: string) => {
    return <FileText className="w-4 h-4" style={{ color: 'var(--stash-text-secondary)' }} />;
  };

  if (node.type === 'folder') {
    return (
      <div>
        <div
          className="w-full flex items-center gap-2 px-3 py-1.5 transition-colors duration-150"
          style={{
            paddingLeft: `${level * 16 + 12}px`,
            backgroundColor: isSelected ? 'var(--stash-bg-surface)' : 'transparent',
            color: 'var(--stash-text-primary)',
            borderLeft: isSelected ? '3px solid var(--stash-accent)' : '3px solid transparent'
          }}
          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = isSelected ? 'var(--stash-bg-surface)' : 'var(--stash-bg-hover)'}
          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = isSelected ? 'var(--stash-bg-surface)' : 'transparent'}
        >
          <button
            onClick={(e) => {
              e.stopPropagation();
              setIsExpanded(!isExpanded);
            }}
            className="flex items-center justify-center w-4 h-4"
          >
            {isExpanded ? (
              <ChevronDown className="w-4 h-4" style={{ color: 'var(--stash-text-secondary)' }} />
            ) : (
              <ChevronRight className="w-4 h-4" style={{ color: 'var(--stash-text-secondary)' }} />
            )}
          </button>
          <button
            onClick={() => onSelectFile(node)}
            className="flex items-center gap-2 flex-1 min-w-0"
          >
            {isExpanded ? (
              <FolderOpen className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--stash-accent)' }} />
            ) : (
              <Folder className="w-4 h-4 flex-shrink-0" style={{ color: 'var(--stash-accent)' }} />
            )}
            <span className="text-sm truncate">{node.name}</span>
          </button>
        </div>
        {isExpanded && node.children && (
          <div>
            {node.children.map((child) => (
              <FileTreeItem
                key={child.id}
                node={child}
                level={level + 1}
                selectedFile={selectedFile}
                onSelectFile={onSelectFile}
                onMoveItem={onMoveItem}
                onDeleteItem={onDeleteItem}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <button
      onClick={() => onSelectFile(node)}
      className="w-full flex items-center gap-2 px-3 py-1.5 transition-colors duration-150 relative"
      style={{
        paddingLeft: `${level * 16 + 12}px`,
        backgroundColor: isSelected ? 'var(--stash-bg-surface)' : 'transparent',
        color: 'var(--stash-text-primary)',
        borderLeft: isSelected ? '3px solid var(--stash-accent)' : '3px solid transparent'
      }}
      onMouseEnter={(e) => {
        if (!isSelected) e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
      }}
      onMouseLeave={(e) => {
        if (!isSelected) e.currentTarget.style.backgroundColor = 'transparent';
      }}
    >
      <div className="w-4 h-4 flex items-center justify-center">
        {getFileIcon(node.extension)}
      </div>
      <span className="text-sm truncate">{node.name}</span>
    </button>
  );
}

export function FileTree({ tree, selectedFile, onSelectFile, onClearSelection, onNewDocument, onOpenSettings, onMoveItem, onDeleteItem, gitInfo }: FileTreeProps) {
  const [searchQuery, setSearchQuery] = useState('');

  const filterTree = (nodes: FileNode[], query: string): FileNode[] => {
    if (!query) return nodes;

    return nodes.reduce<FileNode[]>((acc, node) => {
      if (node.type === 'file' && node.name.toLowerCase().includes(query.toLowerCase())) {
        acc.push(node);
      } else if (node.type === 'folder' && node.children) {
        const filteredChildren = filterTree(node.children, query);
        if (filteredChildren.length > 0) {
          acc.push({ ...node, children: filteredChildren });
        }
      }
      return acc;
    }, []);
  };

  const filteredTree = filterTree(tree, searchQuery);

  return (
    <div className="h-full flex flex-col" style={{ backgroundColor: 'var(--stash-bg-surface)' }}>
      {/* Header */}
      <div className="p-4 border-b" style={{ borderColor: 'var(--stash-border)' }}>
        <button
          onClick={onNewDocument}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-md transition-all duration-150 mb-3"
          style={{
            backgroundColor: 'var(--stash-accent)',
            color: 'var(--stash-bg-base)'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.opacity = '0.9';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.opacity = '1';
          }}
        >
          <Plus className="w-4 h-4" />
          <span className="text-sm">New Document</span>
        </button>

        {/* Search */}
        <div className="relative">
          <Search
            className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4"
            style={{ color: 'var(--stash-text-secondary)' }}
          />
          <input
            type="text"
            placeholder="Search files..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-3 py-2 rounded-md text-sm outline-none transition-all duration-150"
            style={{
              backgroundColor: 'var(--stash-bg-base)',
              color: 'var(--stash-text-primary)',
              border: '1px solid var(--stash-border)'
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = 'var(--stash-accent)';
              e.currentTarget.style.boxShadow = '0 0 0 2px rgba(148, 226, 213, 0.1)';
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = 'var(--stash-border)';
              e.currentTarget.style.boxShadow = 'none';
            }}
          />
        </div>
      </div>

      {/* Branch/Activity Button */}
      {gitInfo && (
        <button
          onClick={() => {
            if (onClearSelection) {
              onClearSelection();
            }
          }}
          className="flex items-center justify-between px-3 py-2.5 border-b transition-colors duration-150"
          style={{ 
            borderColor: 'var(--stash-border)',
            backgroundColor: !selectedFile ? 'var(--stash-bg-hover)' : 'transparent'
          }}
          onMouseEnter={(e) => {
            if (selectedFile) {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
            }
          }}
          onMouseLeave={(e) => {
            if (selectedFile) {
              e.currentTarget.style.backgroundColor = 'transparent';
            }
          }}
        >
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <ChevronRight 
              className="w-4 h-4 flex-shrink-0" 
              style={{ color: 'var(--stash-text-secondary)' }} 
            />
            <GitBranch 
              className="w-4 h-4 flex-shrink-0" 
              style={{ color: 'var(--stash-accent)' }} 
            />
            <span 
              className="text-sm truncate"
              style={{ color: 'var(--stash-text-primary)' }}
            >
              Overview
            </span>
          </div>
          <div 
            className="flex items-center justify-center w-5 h-5 text-xs rounded flex-shrink-0"
            style={{ 
              backgroundColor: 'var(--stash-bg-base)',
              color: 'var(--stash-accent)' 
            }}
          >
            {gitInfo.changes.length}
          </div>
        </button>
      )}

      {/* File Tree */}
      <div className="flex-1 overflow-y-auto">
        <div className="py-2">
          {filteredTree.map((node) => (
            <FileTreeItem
              key={node.id}
              node={node}
              level={0}
              selectedFile={selectedFile}
              onSelectFile={onSelectFile}
              onMoveItem={onMoveItem}
              onDeleteItem={onDeleteItem}
            />
          ))}
        </div>
      </div>

      {/* User Badge */}
      <UserBadge
        name="Dylan Turner"
        email="dylan@example.com"
        onOpenSettings={onOpenSettings}
      />
    </div>
  );
}