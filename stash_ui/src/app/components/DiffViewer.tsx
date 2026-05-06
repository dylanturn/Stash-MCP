import React, { useState } from 'react';
import { X, FileText, FilePlus, FileX, TrendingUp, Folder, ChevronRight, ChevronDown, GitCommit, Clock, User, Bot } from 'lucide-react';
import { DiffLine, GitChangeStatus, GitChange } from '../mockData/gitChanges';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';

interface CommitInfo {
  hash: string;
  message: string;
  author: string;
  date: string;
  isAgent?: boolean;
  agentName?: string;
}

interface DiffViewerProps {
  changes: GitChange[];
  initialFileId?: string;
  commitInfo?: CommitInfo;
  onClose: () => void;
}

export function DiffViewer({ changes, initialFileId, commitInfo, onClose }: DiffViewerProps) {
  const [selectedFileId, setSelectedFileId] = useState<string>(initialFileId || changes[0]?.id);
  const selectedFile = changes.find(c => c.id === selectedFileId);

  // Build a directory tree structure from flat file paths
  interface TreeNode {
    name: string;
    path: string;
    isDirectory: boolean;
    children?: TreeNode[];
    change?: GitChange;
  }

  const buildTree = (changes: GitChange[]): TreeNode[] => {
    const root: { [key: string]: TreeNode } = {};

    changes.forEach(change => {
      const parts = change.path.split('/').filter(p => p);
      let current = root;

      parts.forEach((part, index) => {
        const isFile = index === parts.length - 1;
        const path = '/' + parts.slice(0, index + 1).join('/');

        if (!current[part]) {
          current[part] = {
            name: part,
            path,
            isDirectory: !isFile,
            children: isFile ? undefined : {},
            change: isFile ? change : undefined,
          };
        }

        if (!isFile && current[part].children) {
          current = current[part].children as { [key: string]: TreeNode };
        }
      });
    });

    const convertToArray = (obj: { [key: string]: TreeNode }): TreeNode[] => {
      return Object.values(obj).map(node => ({
        ...node,
        children: node.children ? convertToArray(node.children as { [key: string]: TreeNode }) : undefined,
      }));
    };

    return convertToArray(root);
  };

  const tree = buildTree(changes);

  const getLineStyle = (type: DiffLine['type']): React.CSSProperties => {
    switch (type) {
      case 'add':
        return {
          backgroundColor: 'rgba(166, 227, 161, 0.1)',
        };
      case 'delete':
        return {
          backgroundColor: 'rgba(243, 139, 168, 0.1)',
        };
      default:
        return {};
    }
  };

  const getLinePrefix = (type: DiffLine['type']) => {
    switch (type) {
      case 'add': return '+';
      case 'delete': return '-';
      default: return ' ';
    }
  };

  const getStatusIcon = (status: GitChangeStatus) => {
    switch (status) {
      case 'added': return <FilePlus className="w-3.5 h-3.5" style={{ color: '#a6e3a1' }} />;
      case 'deleted': return <FileX className="w-3.5 h-3.5" style={{ color: '#f38ba8' }} />;
      case 'renamed': return <TrendingUp className="w-3.5 h-3.5" style={{ color: '#94e2d5' }} />;
      default: return <FileText className="w-3.5 h-3.5" style={{ color: '#f9e2af' }} />;
    }
  };

  const getStatusLabel = (status: GitChangeStatus) => {
    switch (status) {
      case 'added': return 'Added';
      case 'deleted': return 'Deleted';
      case 'renamed': return 'Renamed';
      default: return 'Modified';
    }
  };

  const getStatusColor = (status: GitChangeStatus) => {
    switch (status) {
      case 'added': return '#a6e3a1';
      case 'deleted': return '#f38ba8';
      case 'renamed': return '#94e2d5';
      default: return '#f9e2af';
    }
  };

  // Tree component
  const FileTreeNode = ({ node, level = 0 }: { node: TreeNode; level?: number }) => {
    const [isExpanded, setIsExpanded] = useState(true);
    const isSelected = node.change?.id === selectedFileId;

    if (node.isDirectory) {
      return (
        <div>
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="w-full flex items-center gap-2 px-2 py-1 text-xs transition-colors duration-150"
            style={{
              paddingLeft: `${level * 12 + 8}px`,
              color: 'var(--stash-text-primary)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            {isExpanded ? (
              <ChevronDown className="w-3.5 h-3.5" style={{ color: 'var(--stash-text-secondary)' }} />
            ) : (
              <ChevronRight className="w-3.5 h-3.5" style={{ color: 'var(--stash-text-secondary)' }} />
            )}
            <Folder className="w-3.5 h-3.5" style={{ color: 'var(--stash-accent)' }} />
            <span className="truncate">{node.name}</span>
          </button>
          {isExpanded && node.children && (
            <div>
              {node.children.map((child, idx) => (
                <FileTreeNode key={idx} node={child} level={level + 1} />
              ))}
            </div>
          )}
        </div>
      );
    }

    return (
      <button
        onClick={() => node.change && setSelectedFileId(node.change.id)}
        className="w-full flex items-center gap-2 px-2 py-1 text-xs transition-colors duration-150"
        style={{
          paddingLeft: `${level * 12 + 8}px`,
          backgroundColor: isSelected ? 'var(--stash-bg-hover)' : 'transparent',
          color: 'var(--stash-text-primary)',
          borderLeft: isSelected ? '2px solid var(--stash-accent)' : '2px solid transparent',
        }}
        onMouseEnter={(e) => {
          if (!isSelected) {
            e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
          }
        }}
        onMouseLeave={(e) => {
          if (!isSelected) {
            e.currentTarget.style.backgroundColor = 'transparent';
          }
        }}
      >
        {node.change && getStatusIcon(node.change.status)}
        <span className="truncate flex-1 text-left">{node.name}</span>
        {node.change && (
          <div className="flex items-center gap-1.5 text-xs flex-shrink-0">
            {(node.change.additions || 0) > 0 && (
              <span style={{ color: '#a6e3a1' }}>+{node.change.additions}</span>
            )}
            {(node.change.deletions || 0) > 0 && (
              <span style={{ color: '#f38ba8' }}>-{node.change.deletions}</span>
            )}
          </div>
        )}
      </button>
    );
  };

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: 'var(--stash-bg-surface)' }}>
      {/* Commit Info Header (if available) */}
      {commitInfo && (
        <div
          className="px-5 py-4 border-b flex-shrink-0"
          style={{ borderColor: 'var(--stash-border)' }}
        >
          <div className="flex items-start gap-3">
            <div
              className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
              style={{ backgroundColor: 'var(--stash-accent)' }}
            >
              <GitCommit className="w-4 h-4" style={{ color: 'var(--stash-bg-base)' }} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium mb-1" style={{ color: 'var(--stash-text-primary)' }}>
                {commitInfo.message}
              </div>
              <div className="flex items-center gap-3 text-xs flex-wrap" style={{ color: 'var(--stash-text-secondary)' }}>
                <div className="flex items-center gap-1.5">
                  <User className="w-3.5 h-3.5" />
                  <span>{commitInfo.author}</span>
                </div>
                {commitInfo.isAgent && commitInfo.agentName && (
                  <div
                    className="flex items-center gap-1 px-1.5 py-0.5 rounded"
                    style={{
                      backgroundColor: 'var(--stash-accent)',
                      color: 'var(--stash-bg-base)',
                    }}
                  >
                    <Bot className="w-3 h-3" />
                    <span className="font-medium">{commitInfo.agentName}</span>
                  </div>
                )}
                <div className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" />
                  <span>{new Date(commitInfo.date).toLocaleString()}</span>
                </div>
                <div className="flex items-center gap-1.5 font-mono">
                  <span>{commitInfo.hash}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
      
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar - File tree */}
        <PanelGroup direction="horizontal" className="h-full">
          <Panel 
            id="diff-file-tree" 
            order={1} 
            defaultSize={20} 
            minSize={15} 
            maxSize={40}
            className="border-r flex flex-col flex-shrink-0" 
            style={{ borderColor: 'var(--stash-border)' }}
          >
            <div
              className="px-5 border-b flex-shrink-0 flex flex-col justify-center"
              style={{ 
                borderColor: 'var(--stash-border)',
                minHeight: '60px',
              }}
            >
              <div className="text-xs font-medium" style={{ color: 'var(--stash-text-secondary)' }}>
                Changed Files
              </div>
              <div className="text-sm mt-1" style={{ color: 'var(--stash-text-primary)' }}>
                {changes.length} {changes.length === 1 ? 'file' : 'files'}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto pr-3 auto-hide-scrollbar">
              {tree.map((node, idx) => (
                <FileTreeNode key={idx} node={node} />
              ))}
            </div>
          </Panel>
          
          <PanelResizeHandle 
            className="w-1.5 transition-colors duration-150" 
            style={{ backgroundColor: 'var(--stash-border)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-accent)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-border)';
            }}
          />
          
          {/* Right panel - Diff viewer */}
          <Panel 
            id="diff-content" 
            order={2} 
            defaultSize={80}
            className="flex-1 flex flex-col overflow-hidden"
          >
            {/* Header */}
            <div
              className="px-5 border-b flex items-center justify-between flex-shrink-0"
              style={{ 
                borderColor: 'var(--stash-border)',
                minHeight: '60px',
              }}
            >
              {selectedFile ? (
                <>
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    {getStatusIcon(selectedFile.status)}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span
                          className="text-sm truncate"
                          style={{ color: 'var(--stash-text-primary)' }}
                        >
                          {selectedFile.name}
                        </span>
                        <span
                          className="text-xs px-1.5 py-0.5 rounded flex-shrink-0"
                          style={{
                            backgroundColor: `${getStatusColor(selectedFile.status)}20`,
                            color: getStatusColor(selectedFile.status),
                          }}
                        >
                          {getStatusLabel(selectedFile.status)}
                        </span>
                      </div>
                      <div
                        className="text-xs truncate"
                        style={{ color: 'var(--stash-text-secondary)' }}
                      >
                        {selectedFile.oldPath ? `${selectedFile.oldPath} → ${selectedFile.path}` : selectedFile.path}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 ml-4 flex-shrink-0">
                    <div className="flex items-center gap-2 text-xs">
                      {(selectedFile.additions || 0) > 0 && (
                        <span style={{ color: '#a6e3a1' }}>+{selectedFile.additions}</span>
                      )}
                      {(selectedFile.deletions || 0) > 0 && (
                        <span style={{ color: '#f38ba8' }}>-{selectedFile.deletions}</span>
                      )}
                    </div>
                    <button
                      onClick={onClose}
                      className="p-1.5 rounded transition-colors duration-150"
                      onMouseEnter={(e) => {
                        e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.backgroundColor = 'transparent';
                      }}
                    >
                      <X className="w-4 h-4" style={{ color: 'var(--stash-text-secondary)' }} />
                    </button>
                  </div>
                </>
              ) : (
                <div className="flex items-center justify-between w-full">
                  <span className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
                    Select a file to view changes
                  </span>
                  <button
                    onClick={onClose}
                    className="p-1.5 rounded transition-colors duration-150"
                    onMouseEnter={(e) => {
                      e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.backgroundColor = 'transparent';
                    }}
                  >
                    <X className="w-4 h-4" style={{ color: 'var(--stash-text-secondary)' }} />
                  </button>
                </div>
              )}
            </div>

            {/* Diff Content */}
            <div className="flex-1 overflow-y-auto font-mono text-xs">
              {selectedFile?.diff && selectedFile.diff.length > 0 ? (
                selectedFile.diff.map((line, index) => (
                  <div
                    key={index}
                    className="flex"
                    style={getLineStyle(line.type)}
                  >
                    {/* Line number gutter */}
                    <div
                      className="w-12 flex-shrink-0 px-2 py-0.5 text-right select-none border-r"
                      style={{
                        color: 'var(--stash-text-secondary)',
                        borderColor: 'var(--stash-border)',
                        opacity: 0.6,
                      }}
                    >
                      {line.lineNumber || ''}
                    </div>

                    {/* Prefix column */}
                    <div
                      className="w-6 flex-shrink-0 text-center py-0.5 select-none"
                      style={{
                        color: line.type === 'add' ? '#a6e3a1' : line.type === 'delete' ? '#f38ba8' : 'var(--stash-text-secondary)',
                      }}
                    >
                      {getLinePrefix(line.type)}
                    </div>

                    {/* Content */}
                    <div
                      className="flex-1 py-0.5 pr-4 whitespace-pre"
                      style={{
                        color: line.type === 'context' ? 'var(--stash-text-secondary)' : 'var(--stash-text-primary)',
                      }}
                    >
                      {line.content || '\u00A0'}
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex items-center justify-center h-full" style={{ color: 'var(--stash-text-secondary)' }}>
                  {selectedFile ? 'No diff available for this file' : 'Select a file to view changes'}
                </div>
              )}
            </div>
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );
}