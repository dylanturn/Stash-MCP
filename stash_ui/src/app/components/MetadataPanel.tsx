import React, { useState } from 'react';
import { FileNode } from '../types';
import { Copy, Trash2, FileEdit, GitCommit, User, Calendar, FileCode } from 'lucide-react';
import { TableOfContents, Heading } from './TableOfContents';
import { EndpointsList, Endpoint } from './EndpointsList';
import { SectionsList, Section } from './SectionsList';
import { Accordion } from './Accordion';
import { DiffViewer } from './DiffViewer';
import { GitChange, GitCommit as GitCommitType } from '../mockData/gitChanges';

interface MetadataPanelProps {
  file: FileNode | null;
  onDelete: () => void;
  onRename: () => void;
  onDuplicate: () => void;
  headings?: Heading[];
  activeHeadingId?: string | null;
  onHeadingClick?: (id: string) => void;
  endpoints?: Endpoint[];
  activeEndpointId?: string | null;
  onEndpointClick?: (id: string) => void;
  sections?: Section[];
  activeSectionId?: string | null;
  onSectionClick?: (id: string) => void;
  sectionsTitle?: string;
}

export function MetadataPanel({ 
  file, 
  onDelete, 
  onRename, 
  onDuplicate,
  headings = [],
  activeHeadingId = null,
  onHeadingClick,
  endpoints = [],
  activeEndpointId = null,
  onEndpointClick,
  sections = [],
  activeSectionId = null,
  onSectionClick,
  sectionsTitle = 'Sections'
}: MetadataPanelProps) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [selectedCommit, setSelectedCommit] = useState<{
    commitInfo: GitCommitType;
    changes: GitChange[];
    initialFileId?: string;
  } | null>(null);

  // Auto-minimize metadata when ToC is visible
  const hasToC = headings && headings.length > 0 && onHeadingClick;

  if (!file) {
    return (
      <div
        className="h-full p-6"
        style={{ backgroundColor: 'var(--stash-bg-surface)' }}
      >
        <p className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
          Select a file to view metadata
        </p>
      </div>
    );
  }

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getCharacterCount = () => {
    return file.content?.length || 0;
  };

  const getWordCount = () => {
    if (!file.content) return 0;
    return file.content.split(/\s+/).filter(word => word.length > 0).length;
  };

  const getMimeType = () => {
    const ext = file.extension;
    if (ext === 'md') return 'text/markdown';
    if (ext === 'json') return 'application/json';
    if (ext === 'txt') return 'text/plain';
    return 'text/plain';
  };

  const handleDeleteConfirm = () => {
    onDelete();
    setShowDeleteConfirm(false);
  };

  // Mock commit history for the current file
  const getMockCommitHistory = (): { commit: GitCommitType; changes: GitChange[] }[] => {
    // Create realistic commit history for the current file
    return [
      {
        commit: {
          id: 'commit-1',
          hash: 'a3f7b9c',
          message: 'Updated document structure and added new sections',
          author: 'Sarah Chen',
          date: '2024-03-10T14:30:00Z',
          fileChanges: ['change-1'],
          isAgent: false,
        },
        changes: [
          {
            id: 'change-1',
            path: file.path,
            name: file.name,
            status: 'modified',
            additions: 42,
            deletions: 18,
            diff: [
              { type: 'context', lineNumber: 1, content: '# Document Title' },
              { type: 'delete', content: '## Old Section' },
              { type: 'add', content: '## Introduction' },
              { type: 'add', content: '' },
              { type: 'add', content: 'This section provides an overview of the key concepts.' },
              { type: 'context', lineNumber: 5, content: '' },
              { type: 'context', lineNumber: 6, content: '## Main Content' },
            ],
          },
        ],
      },
      {
        commit: {
          id: 'commit-2',
          hash: '8e2d4f1',
          message: 'Fix typos and improve formatting',
          author: 'Alex Rodriguez',
          date: '2024-03-08T09:15:00Z',
          fileChanges: ['change-2'],
          isAgent: false,
        },
        changes: [
          {
            id: 'change-2',
            path: file.path,
            name: file.name,
            status: 'modified',
            additions: 8,
            deletions: 5,
            diff: [
              { type: 'context', lineNumber: 1, content: '# Document Title' },
              { type: 'delete', content: 'Teh quick brown fox jumps over the lazy dog.' },
              { type: 'add', content: 'The quick brown fox jumps over the lazy dog.' },
              { type: 'context', lineNumber: 3, content: '' },
            ],
          },
        ],
      },
      {
        commit: {
          id: 'commit-3',
          hash: 'c91a6e3',
          message: 'Auto-generated documentation update',
          author: 'MCP Documentation Agent',
          date: '2024-03-05T16:45:00Z',
          fileChanges: ['change-3'],
          isAgent: true,
          agentName: 'doc-sync',
        },
        changes: [
          {
            id: 'change-3',
            path: file.path,
            name: file.name,
            status: 'modified',
            additions: 25,
            deletions: 12,
            diff: [
              { type: 'add', content: '## API Reference' },
              { type: 'add', content: '' },
              { type: 'add', content: 'Auto-generated API documentation for the latest release.' },
              { type: 'context', lineNumber: 8, content: '' },
            ],
          },
        ],
      },
      {
        commit: {
          id: 'commit-4',
          hash: '5b8f2d9',
          message: 'Initial commit - created document',
          author: 'Jordan Park',
          date: '2024-03-01T11:00:00Z',
          fileChanges: ['change-4'],
          isAgent: false,
        },
        changes: [
          {
            id: 'change-4',
            path: file.path,
            name: file.name,
            status: 'added',
            additions: 150,
            deletions: 0,
            diff: [
              { type: 'add', content: '# Document Title' },
              { type: 'add', content: '' },
              { type: 'add', content: 'Initial document content...' },
            ],
          },
        ],
      },
    ];
  };

  const commitHistory = getMockCommitHistory();

  const formatCommitDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays} days ago`;
    if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;
    if (diffDays < 365) return `${Math.floor(diffDays / 30)} months ago`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  const handleCommitClick = (commit: GitCommitType, changes: GitChange[]) => {
    setSelectedCommit({
      commitInfo: commit,
      changes,
      initialFileId: changes[0]?.id,
    });
  };

  return (
    <div
      className="h-full flex flex-col"
      style={{ backgroundColor: 'var(--stash-bg-surface)' }}
    >
      {/* Navigation - Scrollable for large documents */}
      {/* Show ToC for markdown, endpoints for OpenAPI, sections for other viewers */}
      {(hasToC || (endpoints && endpoints.length > 0 && onEndpointClick) || (sections && sections.length > 0 && onSectionClick)) ? (
        <div className="flex-1 overflow-y-auto p-6 pb-0">
          {hasToC && (
            <TableOfContents
              headings={headings}
              activeId={activeHeadingId}
              onHeadingClick={onHeadingClick}
            />
          )}
          {endpoints && endpoints.length > 0 && onEndpointClick && (
            <EndpointsList
              endpoints={endpoints}
              activeId={activeEndpointId}
              onEndpointClick={onEndpointClick}
            />
          )}
          {sections && sections.length > 0 && onSectionClick && (
            <SectionsList
              sections={sections}
              activeId={activeSectionId}
              onSectionClick={onSectionClick}
              title={sectionsTitle}
            />
          )}
        </div>
      ) : (
        // Spacer to push content to bottom when no navigation
        <div className="flex-1" />
      )}

      {/* Document Metadata Accordion - At bottom, defaults to closed */}
      <div 
        className="px-6"
        style={{ 
          borderTop: hasToC ? '1px solid var(--stash-border)' : 'none'
        }}
      >
        <Accordion 
          title="Document Metadata" 
          defaultExpanded={false}
        >
          {/* Metadata Fields */}
          <div className="space-y-4 pb-4">
            <div>
              <div className="text-xs mb-1" style={{ color: 'var(--stash-text-secondary)' }}>
                File Path
              </div>
              <div
                className="text-sm font-mono p-2 rounded"
                style={{
                  backgroundColor: 'var(--stash-bg-base)',
                  color: 'var(--stash-text-primary)',
                  wordBreak: 'break-all'
                }}
              >
                {file.path}
              </div>
            </div>

            <div>
              <div className="text-xs mb-1" style={{ color: 'var(--stash-text-secondary)' }}>
                File Size
              </div>
              <div className="text-sm" style={{ color: 'var(--stash-text-primary)' }}>
                {formatFileSize(file.size || 0)}
              </div>
            </div>

            <div>
              <div className="text-xs mb-1" style={{ color: 'var(--stash-text-secondary)' }}>
                MIME Type
              </div>
              <div className="text-sm" style={{ color: 'var(--stash-text-primary)' }}>
                {getMimeType()}
              </div>
            </div>

            <div>
              <div className="text-xs mb-1" style={{ color: 'var(--stash-text-secondary)' }}>
                Last Modified
              </div>
              <div className="text-sm" style={{ color: 'var(--stash-text-primary)' }}>
                {file.lastModified ? formatDate(file.lastModified) : 'Unknown'}
              </div>
            </div>

            <div className="pt-2 border-t" style={{ borderColor: 'var(--stash-border)' }}>
              <div className="text-xs mb-2" style={{ color: 'var(--stash-text-secondary)' }}>
                Content Stats
              </div>
              <div className="flex justify-between text-sm mb-1">
                <span style={{ color: 'var(--stash-text-secondary)' }}>Characters:</span>
                <span style={{ color: 'var(--stash-text-primary)' }}>{getCharacterCount()}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span style={{ color: 'var(--stash-text-secondary)' }}>Words:</span>
                <span style={{ color: 'var(--stash-text-primary)' }}>{getWordCount()}</span>
              </div>
            </div>
          </div>
        </Accordion>
      </div>

      {/* Document History Accordion */}
      <div className="px-6">
        <Accordion 
          title="Document History" 
          defaultExpanded={false}
        >
          <div className="space-y-2 pb-4">
            {commitHistory.map(({ commit, changes }) => (
              <button
                key={commit.id}
                onClick={() => handleCommitClick(commit, changes)}
                className="w-full text-left p-3 rounded-lg transition-all duration-150"
                style={{
                  backgroundColor: 'var(--stash-bg-base)',
                  border: '1px solid var(--stash-border)',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                  e.currentTarget.style.borderColor = 'var(--stash-accent)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--stash-bg-base)';
                  e.currentTarget.style.borderColor = 'var(--stash-border)';
                }}
              >
                {/* Commit hash with change stats on right */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div
                      className="font-mono text-xs px-2 py-0.5 rounded"
                      style={{
                        backgroundColor: 'var(--stash-bg-surface)',
                        color: 'var(--stash-accent)',
                      }}
                    >
                      {commit.hash}
                    </div>
                  </div>
                  
                  {/* Change stats aligned to right with fixed width */}
                  <div className="flex items-center gap-2 text-xs" style={{ minWidth: '80px', justifyContent: 'flex-end' }}>
                    {changes[0]?.additions !== undefined && changes[0].additions > 0 && (
                      <span style={{ color: '#a6e3a1' }}>
                        +{changes[0].additions}
                      </span>
                    )}
                    {changes[0]?.deletions !== undefined && changes[0].deletions > 0 && (
                      <span style={{ color: '#f38ba8' }}>
                        -{changes[0].deletions}
                      </span>
                    )}
                  </div>
                </div>

                {/* Commit message */}
                <div
                  className="text-sm mb-2 line-clamp-2"
                  style={{ color: 'var(--stash-text-primary)' }}
                >
                  {commit.message}
                </div>

                {/* Author with date below */}
                <div className="flex flex-col gap-1 text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
                  <div className="flex items-center gap-1">
                    <User className="w-3 h-3" />
                    <span>{commit.author}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    <span>{formatCommitDate(commit.date)}</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </Accordion>
      </div>

      {/* Diff Viewer Modal */}
      {selectedCommit && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
          onClick={() => setSelectedCommit(null)}
        >
          <div
            className="w-full max-w-6xl h-[90vh] rounded-lg overflow-hidden"
            style={{ 
              backgroundColor: 'var(--stash-bg-surface)',
              boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <DiffViewer
              changes={selectedCommit.changes}
              initialFileId={selectedCommit.initialFileId}
              commitInfo={selectedCommit.commitInfo}
              onClose={() => setSelectedCommit(null)}
            />
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div
        className="p-6 border-t space-y-2"
        style={{ borderColor: 'var(--stash-border)' }}
      >
        <button
          onClick={onRename}
          className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md text-sm transition-all duration-150"
          style={{
            backgroundColor: 'transparent',
            color: 'var(--stash-text-primary)',
            border: '1px solid var(--stash-border)'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent';
          }}
        >
          <FileEdit className="w-4 h-4" />
          <span>Rename / Move</span>
        </button>

        <button
          onClick={onDuplicate}
          className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md text-sm transition-all duration-150"
          style={{
            backgroundColor: 'transparent',
            color: 'var(--stash-text-primary)',
            border: '1px solid var(--stash-border)'
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent';
          }}
        >
          <Copy className="w-4 h-4" />
          <span>Duplicate</span>
        </button>

        {!showDeleteConfirm ? (
          <button
            onClick={() => setShowDeleteConfirm(true)}
            className="w-full flex items-center gap-3 px-4 py-2.5 rounded-md text-sm transition-all duration-150"
            style={{
              backgroundColor: 'transparent',
              color: 'var(--stash-destructive)',
              border: '1px solid var(--stash-destructive)'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(243, 139, 168, 0.1)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <Trash2 className="w-4 h-4" />
            <span>Delete</span>
          </button>
        ) : (
          <div
            className="p-3 rounded-md"
            style={{
              backgroundColor: 'var(--stash-bg-elevated)',
              border: '1px solid var(--stash-destructive)'
            }}
          >
            <div className="text-xs mb-2" style={{ color: 'var(--stash-text-secondary)' }}>
              Delete permanently?
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleDeleteConfirm}
                className="flex-1 px-3 py-2 rounded text-xs transition-all duration-150"
                style={{
                  backgroundColor: 'var(--stash-destructive)',
                  color: 'var(--stash-bg-base)'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.opacity = '0.9';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.opacity = '1';
                }}
              >
                Yes, delete
              </button>
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="flex-1 px-3 py-2 rounded text-xs transition-all duration-150"
                style={{
                  backgroundColor: 'transparent',
                  color: 'var(--stash-text-secondary)',
                  border: '1px solid var(--stash-border)'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent';
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}