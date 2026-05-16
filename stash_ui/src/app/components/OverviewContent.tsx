import React, { useMemo } from 'react';
import { FileText, Folder, Database, Search, GitBranch, GitCommit, FilePlus, FileX, TrendingUp, Clock, Bot } from 'lucide-react';
import { FileNode } from '../types';
import { GitBranchInfo, GitChange, GitCommit as GitCommitType } from '../mockData/gitChanges';
import { DiffViewer } from './DiffViewer';

interface OverviewContentProps {
  fileTree: FileNode[];
  onSelectFile: (path: string) => void;
  gitInfo?: GitBranchInfo;
}

/** Count total files and folders recursively. */
function countNodes(nodes: FileNode[]): { files: number; folders: number } {
  let files = 0;
  let folders = 0;
  for (const node of nodes) {
    if (node.type === 'folder') {
      folders++;
      if (node.children) {
        const child = countNodes(node.children);
        files += child.files;
        folders += child.folders;
      }
    } else {
      files++;
    }
  }
  return { files, folders };
}

/** Collect all files (flat) for the recent-files list. */
function collectFiles(nodes: FileNode[]): FileNode[] {
  const out: FileNode[] = [];
  for (const node of nodes) {
    if (node.type === 'file') {
      out.push(node);
    } else if (node.children) {
      out.push(...collectFiles(node.children));
    }
  }
  return out;
}

/** Group files by extension. */
function groupByExtension(files: FileNode[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const f of files) {
    const ext = f.extension ?? 'other';
    counts[ext] = (counts[ext] ?? 0) + 1;
  }
  return counts;
}

// ---------------------------------------------------------------------------
// Sub-component: file-stats overview (shown when git tracking is disabled)
// ---------------------------------------------------------------------------

function FileStatsOverview({ fileTree, onSelectFile }: { fileTree: FileNode[]; onSelectFile: (path: string) => void }) {
  const { files: totalFiles, folders: totalFolders } = useMemo(
    () => countNodes(fileTree),
    [fileTree]
  );
  const allFiles = useMemo(() => collectFiles(fileTree), [fileTree]);
  const extensionCounts = useMemo(() => groupByExtension(allFiles), [allFiles]);

  const sortedExtensions = useMemo(
    () =>
      Object.entries(extensionCounts)
        .sort(([, a], [, b]) => b - a)
        .slice(0, 10),
    [extensionCounts]
  );

  return (
    <>
      {/* Header */}
      <div className="mb-8">
        <h1
          className="text-3xl mb-2"
          style={{ color: 'var(--stash-text-bright)' }}
        >
          Stash Overview
        </h1>
        <p
          className="text-sm"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          Your content store at a glance
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        <div
          className="rounded-lg p-5 border"
          style={{
            backgroundColor: 'var(--stash-bg-surface)',
            borderColor: 'var(--stash-border)',
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <FileText className="w-4 h-4" style={{ color: 'var(--stash-accent)' }} />
            <span className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
              Files
            </span>
          </div>
          <div className="text-2xl font-medium" style={{ color: 'var(--stash-text-bright)' }}>
            {totalFiles}
          </div>
        </div>

        <div
          className="rounded-lg p-5 border"
          style={{
            backgroundColor: 'var(--stash-bg-surface)',
            borderColor: 'var(--stash-border)',
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Folder className="w-4 h-4" style={{ color: 'var(--stash-accent)' }} />
            <span className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
              Folders
            </span>
          </div>
          <div className="text-2xl font-medium" style={{ color: 'var(--stash-text-bright)' }}>
            {totalFolders}
          </div>
        </div>

        <div
          className="rounded-lg p-5 border"
          style={{
            backgroundColor: 'var(--stash-bg-surface)',
            borderColor: 'var(--stash-border)',
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Database className="w-4 h-4" style={{ color: 'var(--stash-accent)' }} />
            <span className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
              File Types
            </span>
          </div>
          <div className="text-2xl font-medium" style={{ color: 'var(--stash-text-bright)' }}>
            {Object.keys(extensionCounts).length}
          </div>
        </div>
      </div>

      {/* File Types Breakdown */}
      {sortedExtensions.length > 0 && (
        <div
          className="rounded-lg border overflow-hidden mb-8"
          style={{
            backgroundColor: 'var(--stash-bg-surface)',
            borderColor: 'var(--stash-border)',
          }}
        >
          <div
            className="px-6 py-4 border-b"
            style={{ borderColor: 'var(--stash-border)' }}
          >
            <h3 className="text-lg" style={{ color: 'var(--stash-text-primary)' }}>
              Content by Type
            </h3>
          </div>
          <div className="p-4 space-y-2">
            {sortedExtensions.map(([ext, count]) => {
              const pct = totalFiles > 0 ? (count / totalFiles) * 100 : 0;
              return (
                <div key={ext} className="flex items-center gap-3">
                  <span
                    className="text-xs font-mono w-16 text-right"
                    style={{ color: 'var(--stash-text-secondary)' }}
                  >
                    .{ext}
                  </span>
                  <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${pct}%`,
                        backgroundColor: 'var(--stash-accent)',
                        minWidth: '4px',
                      }}
                    />
                  </div>
                  <span
                    className="text-xs w-8 text-right"
                    style={{ color: 'var(--stash-text-secondary)' }}
                  >
                    {count}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* All Files List */}
      {allFiles.length > 0 && (
        <div
          className="rounded-lg border overflow-hidden"
          style={{
            backgroundColor: 'var(--stash-bg-surface)',
            borderColor: 'var(--stash-border)',
          }}
        >
          <div
            className="px-6 py-4 border-b"
            style={{ borderColor: 'var(--stash-border)' }}
          >
            <h3 className="text-lg" style={{ color: 'var(--stash-text-primary)' }}>
              All Files
            </h3>
          </div>
          <div className="p-4 space-y-1 max-h-[500px] overflow-y-auto">
            {allFiles.map((file) => (
              <button
                key={file.id}
                onClick={() => onSelectFile(file.path)}
                className="w-full flex items-center gap-2 px-3 py-2 rounded text-left transition-colors duration-150"
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent';
                }}
              >
                <FileText
                  className="w-4 h-4 flex-shrink-0"
                  style={{ color: 'var(--stash-text-secondary)' }}
                />
                <span
                  className="text-sm truncate"
                  style={{ color: 'var(--stash-text-primary)' }}
                >
                  {file.path}
                </span>
                {file.extension && (
                  <span
                    className="text-xs px-1.5 py-0.5 rounded flex-shrink-0"
                    style={{
                      backgroundColor: 'var(--stash-bg-base)',
                      color: 'var(--stash-text-secondary)',
                    }}
                  >
                    .{file.extension}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Empty State */}
      {allFiles.length === 0 && (
        <div
          className="rounded-lg border p-12 text-center"
          style={{
            backgroundColor: 'var(--stash-bg-surface)',
            borderColor: 'var(--stash-border)',
          }}
        >
          <Search
            className="w-12 h-12 mx-auto mb-4"
            style={{ color: 'var(--stash-text-secondary)', opacity: 0.5 }}
          />
          <h3
            className="text-lg mb-2"
            style={{ color: 'var(--stash-text-primary)' }}
          >
            No content yet
          </h3>
          <p
            className="text-sm"
            style={{ color: 'var(--stash-text-secondary)' }}
          >
            Create your first document using the "New Document" button in the sidebar.
          </p>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: git overview (shown when git tracking is enabled)
// ---------------------------------------------------------------------------

function GitOverview({ gitInfo, onSelectFile }: { gitInfo: GitBranchInfo; onSelectFile: (path: string) => void }) {
  const [selectedCommit, setSelectedCommit] = React.useState<{
    changes: GitChange[];
    initialFileId?: string;
    commitInfo?: GitCommitType;
  } | null>(null);

  const featureCommits = gitInfo.commits.filter(c => c.branch === 'feature');
  const baseCommits = gitInfo.commits.filter(c => c.branch === 'base');

  const handleFileClick = (change: GitChange, commitId: string) => {
    if (change.diff && change.diff.length > 0) {
      const commit = gitInfo.commits.find(c => c.id === commitId);
      if (commit) {
        const allChanges = commit.branch === 'base'
          ? gitInfo.baseBranchChanges
          : gitInfo.changes;
        const commitChanges = allChanges.filter(c =>
          commit.fileChanges.includes(c.id) && c.diff && c.diff.length > 0
        );
        setSelectedCommit({
          changes: commitChanges,
          initialFileId: change.id,
          commitInfo: commit
        });
      }
    } else {
      onSelectFile(change.path);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'added': return '#a6e3a1';
      case 'modified': return '#f9e2af';
      case 'deleted': return '#f38ba8';
      case 'renamed': return '#94e2d5';
      default: return 'var(--stash-text-secondary)';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'added': return <FilePlus className="w-4 h-4" />;
      case 'deleted': return <FileX className="w-4 h-4" />;
      default: return <FileText className="w-4 h-4" />;
    }
  };

  const totalAdditions = gitInfo.changes.reduce((sum, c) => sum + (c.additions || 0), 0);
  const totalDeletions = gitInfo.changes.reduce((sum, c) => sum + (c.deletions || 0), 0);

  const changesByStatus = {
    added: gitInfo.changes.filter(c => c.status === 'added').length,
    modified: gitInfo.changes.filter(c => c.status === 'modified').length,
    deleted: gitInfo.changes.filter(c => c.status === 'deleted').length,
    renamed: gitInfo.changes.filter(c => c.status === 'renamed').length,
  };

  const renderCommitNode = (commit: GitCommitType, index: number, commitList: GitCommitType[], isBaseBranch: boolean) => {
    const changesSource = isBaseBranch ? gitInfo.baseBranchChanges : gitInfo.changes;
    const commitChanges = changesSource.filter(change =>
      commit.fileChanges.includes(change.id)
    );
    const dotColor = isBaseBranch ? 'var(--stash-text-secondary)' : 'var(--stash-accent)';

    return (
      <div key={commit.id} className="relative">
        {index < commitList.length - 1 && (
          <div
            className="absolute left-[11px] top-6 w-0.5 h-full"
            style={{ backgroundColor: 'var(--stash-border)' }}
          />
        )}

        <div className="flex gap-3">
          <div
            className="w-6 h-6 rounded-full flex-shrink-0 flex items-center justify-center mt-0.5"
            style={{
              backgroundColor: dotColor,
              border: '3px solid var(--stash-bg-surface)'
            }}
          >
            <div
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: 'var(--stash-bg-base)' }}
            />
          </div>

          <div className="flex-1 min-w-0">
            <div className="mb-2">
              <div
                className="text-sm font-medium mb-1"
                style={{ color: 'var(--stash-text-primary)' }}
              >
                {commit.message}
              </div>
              <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
                <span>{commit.author}</span>
                {commit.isAgent && (
                  <>
                    <span>&bull;</span>
                    <div
                      className="flex items-center gap-1 px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor: isBaseBranch ? 'var(--stash-text-secondary)' : 'var(--stash-accent)',
                        color: 'var(--stash-bg-base)'
                      }}
                      title={commit.agentName}
                    >
                      <Bot className="w-3 h-3" />
                      <span className="font-medium">Agent</span>
                    </div>
                  </>
                )}
                <span>&bull;</span>
                <div className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  <span>{new Date(commit.date).toLocaleDateString()}</span>
                </div>
              </div>
              <div
                className="text-xs mt-1 font-mono"
                style={{ color: 'var(--stash-text-secondary)' }}
              >
                {commit.hash}
              </div>
            </div>

            {/* Changed Files in This Commit */}
            <div className="space-y-1">
              {commitChanges.map((change) => (
                <button
                  key={change.id}
                  onClick={() => handleFileClick(change, commit.id)}
                  className="w-full flex items-center gap-2 px-2 py-1.5 rounded text-left transition-colors duration-150"
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }}
                >
                  <div style={{ color: getStatusColor(change.status) }}>
                    {getStatusIcon(change.status)}
                  </div>
                  <span
                    className="text-xs truncate flex-1"
                    style={{ color: 'var(--stash-text-primary)' }}
                  >
                    {change.name}
                  </span>
                  <div className="flex items-center gap-2 text-xs flex-shrink-0">
                    {change.additions! > 0 && (
                      <span style={{ color: '#a6e3a1' }}>+{change.additions}</span>
                    )}
                    {change.deletions! > 0 && (
                      <span style={{ color: '#f38ba8' }}>-{change.deletions}</span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <>
      {/* Header */}
      <div className="mb-8">
        <h1
          className="text-3xl mb-2"
          style={{ color: 'var(--stash-text-bright)' }}
        >
          Stash Overview
        </h1>
        <p
          className="text-sm"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          Track changes and activity in your repository
        </p>
      </div>

      {/* Branch Info Card */}
      <div
        className="rounded-lg p-6 mb-6 border"
        style={{
          backgroundColor: 'var(--stash-bg-surface)',
          borderColor: 'var(--stash-border)'
        }}
      >
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <GitBranch
              className="w-6 h-6"
              style={{ color: 'var(--stash-accent)' }}
            />
            <div>
              <h2
                className="text-xl"
                style={{ color: 'var(--stash-text-primary)' }}
              >
                {gitInfo.currentBranch}
              </h2>
              <p
                className="text-sm mt-0.5"
                style={{ color: 'var(--stash-text-secondary)' }}
              >
                Comparing to {gitInfo.baseBranch}
              </p>
            </div>
          </div>

          {gitInfo.commitsAhead > 0 && (
            <div
              className="flex items-center gap-2 px-3 py-2 rounded"
              style={{
                backgroundColor: 'var(--stash-bg-base)',
                color: 'var(--stash-accent)'
              }}
            >
              <GitCommit className="w-4 h-4" />
              <span className="text-sm font-medium">{gitInfo.commitsAhead} ahead</span>
            </div>
          )}
        </div>

        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="text-2xl font-medium" style={{ color: '#a6e3a1' }}>
              +{totalAdditions}
            </span>
            <span className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
              additions
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-2xl font-medium" style={{ color: '#f38ba8' }}>
              -{totalDeletions}
            </span>
            <span className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
              deletions
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-2xl font-medium" style={{ color: 'var(--stash-text-primary)' }}>
              {gitInfo.changes.length}
            </span>
            <span className="text-sm" style={{ color: 'var(--stash-text-secondary)' }}>
              changed files
            </span>
          </div>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="flex gap-4 mb-6">
        {changesByStatus.added > 0 && (
          <div
            className="flex-1 rounded-lg p-4 border"
            style={{
              backgroundColor: 'var(--stash-bg-surface)',
              borderColor: 'var(--stash-border)'
            }}
          >
            <div className="flex items-center gap-2 mb-2">
              <FilePlus className="w-4 h-4" style={{ color: '#a6e3a1' }} />
              <span className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>Added</span>
            </div>
            <div className="text-2xl font-medium" style={{ color: '#a6e3a1' }}>
              {changesByStatus.added}
            </div>
          </div>
        )}

        {changesByStatus.modified > 0 && (
          <div
            className="flex-1 rounded-lg p-4 border"
            style={{
              backgroundColor: 'var(--stash-bg-surface)',
              borderColor: 'var(--stash-border)'
            }}
          >
            <div className="flex items-center gap-2 mb-2">
              <FileText className="w-4 h-4" style={{ color: '#f9e2af' }} />
              <span className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>Modified</span>
            </div>
            <div className="text-2xl font-medium" style={{ color: '#f9e2af' }}>
              {changesByStatus.modified}
            </div>
          </div>
        )}

        {changesByStatus.deleted > 0 && (
          <div
            className="flex-1 rounded-lg p-4 border"
            style={{
              backgroundColor: 'var(--stash-bg-surface)',
              borderColor: 'var(--stash-border)'
            }}
          >
            <div className="flex items-center gap-2 mb-2">
              <FileX className="w-4 h-4" style={{ color: '#f38ba8' }} />
              <span className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>Deleted</span>
            </div>
            <div className="text-2xl font-medium" style={{ color: '#f38ba8' }}>
              {changesByStatus.deleted}
            </div>
          </div>
        )}

        {changesByStatus.renamed > 0 && (
          <div
            className="flex-1 rounded-lg p-4 border"
            style={{
              backgroundColor: 'var(--stash-bg-surface)',
              borderColor: 'var(--stash-border)'
            }}
          >
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp className="w-4 h-4" style={{ color: '#94e2d5' }} />
              <span className="text-xs" style={{ color: 'var(--stash-text-secondary)' }}>Renamed</span>
            </div>
            <div className="text-2xl font-medium" style={{ color: '#94e2d5' }}>
              {changesByStatus.renamed}
            </div>
          </div>
        )}
      </div>

      {/* Commit Timeline */}
      <div
        className="rounded-lg border overflow-hidden"
        style={{
          backgroundColor: 'var(--stash-bg-surface)',
          borderColor: 'var(--stash-border)'
        }}
      >
        <div className="px-6 py-4 border-b" style={{ borderColor: 'var(--stash-border)' }}>
          <h3 className="text-lg" style={{ color: 'var(--stash-text-primary)' }}>
            Commit Timeline
          </h3>
        </div>

        <div className="p-4 space-y-4 max-h-[600px] overflow-y-auto">
          {/* Branch Timeline Summary */}
          <div className="relative">
            <div
              className="absolute left-[11px] top-6 w-0.5 h-full"
              style={{ backgroundColor: 'var(--stash-border)' }}
            />

            <div className="flex gap-3">
              <div
                className="w-6 h-6 rounded-full flex-shrink-0 flex items-center justify-center mt-0.5"
                style={{
                  backgroundColor: 'var(--stash-accent)',
                  border: '3px solid var(--stash-bg-surface)'
                }}
              >
                <GitBranch className="w-3 h-3" style={{ color: 'var(--stash-bg-base)' }} />
              </div>

              <div className="flex-1 min-w-0">
                <div
                  className="text-sm font-medium mb-2"
                  style={{ color: 'var(--stash-text-primary)' }}
                >
                  Branch: {gitInfo.currentBranch}
                </div>
                <div
                  className="text-xs mb-3"
                  style={{ color: 'var(--stash-text-secondary)' }}
                >
                  {gitInfo.commitsAhead} commits ahead, {gitInfo.commitsBehind} behind {gitInfo.baseBranch}
                </div>

                {/* Mini Timeline */}
                <div className="space-y-2">
                  {featureCommits.slice().reverse().map((commit) => {
                    const commitChanges = gitInfo.changes.filter(change =>
                      commit.fileChanges.includes(change.id)
                    );
                    const commitAdditions = commitChanges.reduce((sum, c) => sum + (c.additions || 0), 0);
                    const commitDeletions = commitChanges.reduce((sum, c) => sum + (c.deletions || 0), 0);

                    return (
                      <div
                        key={commit.id}
                        className="px-3 py-2 rounded"
                        style={{ backgroundColor: 'var(--stash-bg-base)' }}
                      >
                        <div className="flex items-start gap-2 mb-2">
                          <div
                            className="w-2 h-2 rounded-full flex-shrink-0 mt-1.5"
                            style={{ backgroundColor: 'var(--stash-accent)' }}
                          />
                          <div className="flex-1 min-w-0">
                            <div
                              className="text-xs mb-0.5 truncate"
                              style={{ color: 'var(--stash-text-primary)' }}
                            >
                              {commit.message}
                            </div>
                            <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--stash-text-secondary)' }}>
                              <span>{commit.author}</span>
                              {commit.isAgent && (
                                <>
                                  <span>&bull;</span>
                                  <div
                                    className="flex items-center gap-1 px-1.5 py-0.5 rounded"
                                    style={{
                                      backgroundColor: 'var(--stash-accent)',
                                      color: 'var(--stash-bg-base)'
                                    }}
                                    title={commit.agentName}
                                  >
                                    <Bot className="w-3 h-3" />
                                    <span className="font-medium">Agent</span>
                                  </div>
                                </>
                              )}
                              <span>&bull;</span>
                              <span className="font-mono">{commit.hash}</span>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 text-xs flex-shrink-0">
                            {commitAdditions > 0 && (
                              <span style={{ color: '#a6e3a1' }}>+{commitAdditions}</span>
                            )}
                            {commitDeletions > 0 && (
                              <span style={{ color: '#f38ba8' }}>-{commitDeletions}</span>
                            )}
                          </div>
                        </div>

                        {/* Files Changed */}
                        <div className="ml-4 space-y-1">
                          {commitChanges.map((change) => (
                            <button
                              key={change.id}
                              onClick={() => handleFileClick(change, commit.id)}
                              className="w-full flex items-center gap-2 px-2 py-1 rounded text-left transition-colors duration-150"
                              onMouseEnter={(e) => {
                                e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
                              }}
                              onMouseLeave={(e) => {
                                e.currentTarget.style.backgroundColor = 'transparent';
                              }}
                            >
                              <div style={{ color: getStatusColor(change.status) }}>
                                {getStatusIcon(change.status)}
                              </div>
                              <span
                                className="text-xs truncate flex-1"
                                style={{ color: 'var(--stash-text-primary)' }}
                              >
                                {change.name}
                              </span>
                              <div className="flex items-center gap-2 text-xs flex-shrink-0">
                                {change.additions! > 0 && (
                                  <span style={{ color: '#a6e3a1' }}>+{change.additions}</span>
                                )}
                                {change.deletions! > 0 && (
                                  <span style={{ color: '#f38ba8' }}>-{change.deletions}</span>
                                )}
                              </div>
                            </button>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>

          {/* Feature Branch Commits */}
          {featureCommits.map((commit, index) =>
            renderCommitNode(commit, index, featureCommits, false)
          )}

          {/* Branch Point Divider */}
          <div className="relative">
            <div
              className="absolute left-[11px] top-6 w-0.5 h-full"
              style={{ backgroundColor: 'var(--stash-border)' }}
            />
            <div className="flex gap-3">
              <div
                className="w-6 h-6 rounded-full flex-shrink-0 flex items-center justify-center mt-0.5"
                style={{
                  backgroundColor: 'var(--stash-border)',
                  border: '3px solid var(--stash-bg-surface)'
                }}
              >
                <GitBranch className="w-3 h-3" style={{ color: 'var(--stash-bg-base)' }} />
              </div>
              <div className="flex-1 min-w-0 py-1">
                <div
                  className="text-sm font-medium"
                  style={{ color: 'var(--stash-text-secondary)' }}
                >
                  Branched from {gitInfo.baseBranch}
                </div>
                {gitInfo.branchPointDate && (
                  <div className="flex items-center gap-1 text-xs mt-0.5" style={{ color: 'var(--stash-text-secondary)' }}>
                    <Clock className="w-3 h-3" />
                    <span>{new Date(gitInfo.branchPointDate).toLocaleDateString()}</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Base Branch Commits */}
          {baseCommits.map((commit, index) =>
            renderCommitNode(commit, index, baseCommits, true)
          )}
        </div>
      </div>

      {/* Diff Viewer Modal */}
      {selectedCommit && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.7)' }}
          onClick={() => setSelectedCommit(null)}
        >
          <div
            className="w-full max-w-5xl h-[80vh] rounded-lg border overflow-hidden"
            style={{
              backgroundColor: 'var(--stash-bg-surface)',
              borderColor: 'var(--stash-border)',
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
    </>
  );
}

// ---------------------------------------------------------------------------
// Main export: delegates to the appropriate sub-component
// ---------------------------------------------------------------------------

export function OverviewContent({ fileTree, onSelectFile, gitInfo }: OverviewContentProps) {
  return (
    <div
      className="h-full overflow-y-auto"
      style={{ backgroundColor: 'var(--stash-bg-base)' }}
    >
      <div className="max-w-5xl mx-auto px-8 py-12">
        {gitInfo ? (
          <GitOverview gitInfo={gitInfo} onSelectFile={onSelectFile} />
        ) : (
          <FileStatsOverview fileTree={fileTree} onSelectFile={onSelectFile} />
        )}
      </div>
    </div>
  );
}
