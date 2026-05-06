import React, { useState, useEffect, useCallback } from 'react';
import { FileNode, apiTreeToFileNodes } from '../types';
import { getTree, getContent, putContent, deleteContent, createContent, moveContent, getGitOverview } from '../../api/client';
import { FileTree } from '../components/FileTree';
import { DocumentViewer } from '../components/DocumentViewer';
import { DirectoryListing } from '../components/DirectoryListing';
import { MetadataPanel } from '../components/MetadataPanel';
import { OverviewContent } from '../components/OverviewContent';
import { NewDocumentModal } from '../components/NewDocumentModal';
import { OrganizationSettingsModal } from '../components/OrganizationSettingsModal';
import { Heading } from '../components/TableOfContents';
import { Endpoint } from '../components/EndpointsList';
import { Section } from '../components/SectionsList';
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import { GitBranchInfo } from '../mockData/gitChanges';

export function DocumentsPage() {
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<FileNode | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isContentLoading, setIsContentLoading] = useState(false);
  const [isLeftPanelOpen, setIsLeftPanelOpen] = useState(true);
  const [isRightPanelOpen, setIsRightPanelOpen] = useState(true);
  const [isNewDocModalOpen, setIsNewDocModalOpen] = useState(false);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [headings, setHeadings] = useState<Heading[]>([]);
  const [activeHeadingId, setActiveHeadingId] = useState<string | null>(null);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [activeEndpointId, setActiveEndpointId] = useState<string | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const [sectionsTitle, setSectionsTitle] = useState<string>('Sections');
  const [gitInfo, setGitInfo] = useState<GitBranchInfo | null>(null);

  // Fetch the file tree from the API on mount
  const refreshTree = useCallback(async () => {
    try {
      const tree = await getTree();
      setFileTree(apiTreeToFileNodes(tree));
    } catch (err) {
      console.error('Failed to load file tree:', err);
      toast.error('Failed to load file tree');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshTree();
    getGitOverview().then((data) => {
      if (data) setGitInfo(data as GitBranchInfo);
    });
  }, [refreshTree]);

  // Clear navigation when a directory is selected
  useEffect(() => {
    if (selectedFile?.type === 'folder') {
      setHeadings([]);
      setActiveHeadingId(null);
      setEndpoints([]);
      setActiveEndpointId(null);
      setSections([]);
      setActiveSectionId(null);
    }
  }, [selectedFile]);

  // Load file content from the API when a file is selected
  const handleSelectFile = useCallback(async (file: FileNode) => {
    if (file.type === 'folder') {
      setSelectedFile(file);
      return;
    }

    // If content is already loaded, just select it
    if (file.content !== undefined) {
      setSelectedFile(file);
      return;
    }

    setIsContentLoading(true);
    setSelectedFile(file);

    try {
      const data = await getContent(file.path);
      const enrichedFile: FileNode = {
        ...file,
        content: data.content ?? '',
        size: data.content ? new TextEncoder().encode(data.content).length : 0,
        lastModified: data.updated_at ?? undefined,
        mimeType: data.mime_type ?? undefined,
      };
      setSelectedFile(enrichedFile);

      // Also update the file in the tree so re-selecting doesn't re-fetch
      setFileTree((prev) => updateFileInTree(prev, file.id, enrichedFile));
    } catch (err) {
      console.error('Failed to load file content:', err);
      toast.error('Failed to load file content');
    } finally {
      setIsContentLoading(false);
    }
  }, []);

  const updateFileInTree = (
    nodes: FileNode[],
    fileId: string,
    replacement: FileNode
  ): FileNode[] => {
    return nodes.map((node) => {
      if (node.id === fileId) return replacement;
      if (node.type === 'folder' && node.children) {
        return {
          ...node,
          children: updateFileInTree(node.children, fileId, replacement),
        };
      }
      return node;
    });
  };

  const handleSaveFile = async (content: string) => {
    if (!selectedFile) return;

    try {
      await putContent(selectedFile.path, content);
      const updatedFile: FileNode = {
        ...selectedFile,
        content,
        size: new TextEncoder().encode(content).length,
        lastModified: new Date().toISOString(),
      };
      setSelectedFile(updatedFile);
      setFileTree((prev) => updateFileInTree(prev, selectedFile.id, updatedFile));
      toast.success('Document saved');
    } catch (err) {
      console.error('Failed to save file:', err);
      toast.error('Failed to save document');
    }
  };

  const handleDeleteFile = async () => {
    if (!selectedFile) return;

    try {
      await deleteContent(selectedFile.path);
      setSelectedFile(null);
      await refreshTree();
      toast.success('Document deleted');
    } catch (err) {
      console.error('Failed to delete file:', err);
      toast.error('Failed to delete document');
    }
  };

  const handleRenameFile = () => {
    toast.info('Rename functionality coming soon');
  };

  const handleDuplicateFile = () => {
    if (!selectedFile) return;
    toast.info('Duplicate functionality coming soon');
  };

  const handleMoveItem = async (item: FileNode) => {
    const destination = window.prompt(`Move "${item.name}" to (new path):`, item.path);
    if (!destination || destination === item.path) return;

    try {
      await moveContent(item.path, destination);
      await refreshTree();
      toast.success(`Moved to ${destination}`);
    } catch (err) {
      console.error('Failed to move item:', err);
      toast.error('Failed to move item');
    }
  };

  const handleDeleteItemFromListing = async (item: FileNode) => {
    const itemType = item.type === 'folder' ? 'directory' : 'file';
    const confirmed = window.confirm(`Are you sure you want to delete ${itemType} "${item.name}"?`);
    if (!confirmed) return;

    try {
      await deleteContent(item.path);
      if (selectedFile?.id === item.id) {
        setSelectedFile(null);
      }
      await refreshTree();
      toast.success(`${item.type === 'folder' ? 'Directory' : 'File'} deleted`);
    } catch (err) {
      console.error('Failed to delete item:', err);
      toast.error('Failed to delete item');
    }
  };

  const handleCreateDocument = async (path: string, content: string, _template: string) => {
    try {
      await createContent(path, content);
      await refreshTree();

      // Select the newly created file
      const newFile: FileNode = {
        id: path,
        name: path.split('/').pop() || 'untitled',
        type: 'file',
        path,
        extension: path.split('.').pop(),
        content,
        size: new TextEncoder().encode(content).length,
        lastModified: new Date().toISOString(),
      };
      setSelectedFile(newFile);
      setIsNewDocModalOpen(false);
      toast.success('Document created');
    } catch (err) {
      console.error('Failed to create document:', err);
      toast.error('Failed to create document');
    }
  };

  const handleHeadingClick = (id: string) => {
    const element = document.getElementById(id);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  // Find a file in the tree by path (for overview click-through)
  const findFileByPath = useCallback(
    (nodes: FileNode[], targetPath: string): FileNode | null => {
      for (const node of nodes) {
        if (node.path === targetPath) return node;
        if (node.type === 'folder' && node.children) {
          const found = findFileByPath(node.children, targetPath);
          if (found) return found;
        }
      }
      return null;
    },
    []
  );

  if (isLoading) {
    return (
      <div
        className="h-screen w-screen flex items-center justify-center"
        style={{ backgroundColor: 'var(--stash-bg-base)' }}
      >
        <div className="flex items-center gap-3">
          <Loader2
            className="w-5 h-5 animate-spin"
            style={{ color: 'var(--stash-accent)' }}
          />
          <span style={{ color: 'var(--stash-text-secondary)' }}>
            Loading content...
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      className="h-screen w-screen flex flex-col overflow-hidden"
      style={{ backgroundColor: 'var(--stash-bg-base)' }}
    >
      {/* Header */}
      <header
        className="flex items-center justify-between px-6 py-4 border-b"
        style={{
          backgroundColor: 'var(--stash-bg-surface)',
          borderColor: 'var(--stash-border)',
        }}
      >
        <div className="flex items-center gap-3">
          <svg width="160" height="32" viewBox="0 0 320 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="2" y="8" width="38" height="48" rx="8" fill="#272738" stroke="#94e2d5" strokeWidth="2"/>
            <rect x="7" y="14" width="28" height="34" rx="5" fill="#1e1e2e" stroke="#313244" strokeWidth="1"/>
            <path d="M13 18 L13 42 L31 42 L31 24 L25 18 Z" fill="#272738" stroke="#94e2d5" strokeWidth="1.2" strokeLinejoin="round"/>
            <path d="M25 18 L25 24 L31 24" fill="none" stroke="#94e2d5" strokeWidth="1.2" strokeLinejoin="round"/>
            <line x1="16" y1="28" x2="27" y2="28" stroke="#585b70" strokeWidth="1.2" strokeLinecap="round"/>
            <line x1="16" y1="32" x2="28" y2="32" stroke="#4a4b5e" strokeWidth="1" strokeLinecap="round"/>
            <line x1="16" y1="36" x2="24" y2="36" stroke="#4a4b5e" strokeWidth="1" strokeLinecap="round"/>
            <circle cx="52" cy="16" r="5" fill="#272738" stroke="#94e2d5" strokeWidth="1.5"/>
            <circle cx="52" cy="16" r="2" fill="#94e2d5"/>
            <circle cx="52" cy="32" r="5" fill="#272738" stroke="#94e2d5" strokeWidth="1.5"/>
            <circle cx="52" cy="32" r="2" fill="#94e2d5"/>
            <circle cx="52" cy="48" r="5" fill="#272738" stroke="#94e2d5" strokeWidth="1.5"/>
            <circle cx="52" cy="48" r="2" fill="#94e2d5"/>
            <line x1="40" y1="18" x2="47" y2="16" stroke="#94e2d5" strokeWidth="1" opacity="0.4"/>
            <line x1="40" y1="32" x2="47" y2="32" stroke="#94e2d5" strokeWidth="1" opacity="0.4"/>
            <line x1="40" y1="46" x2="47" y2="48" stroke="#94e2d5" strokeWidth="1" opacity="0.4"/>
            <circle cx="21" cy="14" r="2.5" fill="#1e1e2e" stroke="#94e2d5" strokeWidth="1"/>
            <circle cx="21" cy="14" r="1" fill="#94e2d5"/>
            <text x="70" y="41" fontFamily="-apple-system,BlinkMacSystemFont,'Segoe UI','Helvetica Neue',sans-serif" fontSize="32" fontWeight="600" fill="#cdd6f4" letterSpacing="-0.5">stash</text>
            <text x="147" y="41" fontFamily="-apple-system,BlinkMacSystemFont,'Segoe UI','Helvetica Neue',sans-serif" fontSize="32" fontWeight="300" fill="#94e2d5" letterSpacing="-0.5">-mcp</text>
          </svg>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsLeftPanelOpen(!isLeftPanelOpen)}
            className="p-2 rounded transition-all duration-150"
            style={{ color: 'var(--stash-text-secondary)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
            title={isLeftPanelOpen ? 'Hide file tree' : 'Show file tree'}
          >
            {isLeftPanelOpen ? (
              <PanelLeftClose className="w-5 h-5" />
            ) : (
              <PanelLeftOpen className="w-5 h-5" />
            )}
          </button>
          <button
            onClick={() => setIsRightPanelOpen(!isRightPanelOpen)}
            className="p-2 rounded transition-all duration-150"
            style={{ color: 'var(--stash-text-secondary)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
            title={isRightPanelOpen ? 'Hide metadata panel' : 'Show metadata panel'}
          >
            {isRightPanelOpen ? (
              <PanelRightClose className="w-5 h-5" />
            ) : (
              <PanelRightOpen className="w-5 h-5" />
            )}
          </button>
        </div>
      </header>

      {/* Main Content - Three Panels */}
      <PanelGroup direction="horizontal" className="flex-1">
        {/* Left Panel - File Tree */}
        {isLeftPanelOpen && (
          <>
            <Panel
              id="left-panel"
              order={1}
              defaultSize={20}
              minSize={15}
              maxSize={40}
              className="overflow-hidden border-r"
              style={{
                borderColor: 'var(--stash-border)',
              }}
            >
              <FileTree
                tree={fileTree}
                selectedFile={selectedFile}
                onSelectFile={handleSelectFile}
                onClearSelection={() => setSelectedFile(null)}
                onNewDocument={() => setIsNewDocModalOpen(true)}
                onOpenSettings={() => setIsSettingsModalOpen(true)}
                onMoveItem={handleMoveItem}
                onDeleteItem={handleDeleteItemFromListing}
                gitInfo={gitInfo ?? undefined}
              />
            </Panel>
            <PanelResizeHandle
              className="w-1 hover:w-1.5 transition-all duration-150 relative group"
              style={{
                backgroundColor: 'var(--stash-border)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--stash-accent)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--stash-border)';
              }}
            />
          </>
        )}

        {/* Center Panel - Document Viewer */}
        <Panel id="center-panel" order={2} className="overflow-hidden" minSize={30}>
          {!selectedFile ? (
            <OverviewContent
              fileTree={fileTree}
              onSelectFile={(path) => {
                const file = findFileByPath(fileTree, path);
                if (file) handleSelectFile(file);
              }}
              gitInfo={gitInfo ?? undefined}
            />
          ) : isContentLoading ? (
            <div
              className="h-full flex items-center justify-center"
              style={{ backgroundColor: 'var(--stash-bg-base)' }}
            >
              <div className="flex items-center gap-3">
                <Loader2
                  className="w-5 h-5 animate-spin"
                  style={{ color: 'var(--stash-accent)' }}
                />
                <span style={{ color: 'var(--stash-text-secondary)' }}>
                  Loading document...
                </span>
              </div>
            </div>
          ) : selectedFile.type === 'folder' ? (
            <DirectoryListing
              directory={selectedFile}
              onSelectItem={handleSelectFile}
              onDeleteItem={handleDeleteItemFromListing}
              onMoveItem={handleMoveItem}
            />
          ) : (
            <DocumentViewer
              file={selectedFile}
              onSave={handleSaveFile}
              onNavigate={(path) => {
                const target = findFileByPath(fileTree, path);
                if (target) {
                  handleSelectFile(target);
                } else {
                  toast.error(`File not found: ${path}`);
                }
              }}
              onHeadingsChange={setHeadings}
              onActiveHeadingChange={setActiveHeadingId}
              onEndpointsChange={setEndpoints}
              onActiveEndpointChange={setActiveEndpointId}
              onSectionsChange={setSections}
              onActiveSectionChange={setActiveSectionId}
              onSectionsTitleChange={setSectionsTitle}
            />
          )}
        </Panel>

        {/* Right Panel - Metadata */}
        {isRightPanelOpen && selectedFile && (
          <>
            <PanelResizeHandle
              className="w-1 hover:w-1.5 transition-all duration-150 relative group"
              style={{
                backgroundColor: 'var(--stash-border)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--stash-accent)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--stash-border)';
              }}
            />
            <Panel
              id="right-panel"
              order={3}
              defaultSize={20}
              minSize={15}
              maxSize={40}
              className="overflow-hidden border-l"
              style={{
                borderColor: 'var(--stash-border)',
              }}
            >
              <MetadataPanel
                file={selectedFile}
                onDelete={handleDeleteFile}
                onRename={handleRenameFile}
                onDuplicate={handleDuplicateFile}
                headings={headings}
                activeHeadingId={activeHeadingId}
                onHeadingClick={handleHeadingClick}
                endpoints={endpoints}
                activeEndpointId={activeEndpointId}
                onEndpointClick={handleHeadingClick}
                sections={sections}
                activeSectionId={activeSectionId}
                onSectionClick={handleHeadingClick}
                sectionsTitle={sectionsTitle}
              />
            </Panel>
          </>
        )}
      </PanelGroup>

      {/* New Document Modal */}
      <NewDocumentModal
        isOpen={isNewDocModalOpen}
        onClose={() => setIsNewDocModalOpen(false)}
        onCreate={handleCreateDocument}
      />

      {/* Organization Settings Modal */}
      <OrganizationSettingsModal
        isOpen={isSettingsModalOpen}
        onClose={() => setIsSettingsModalOpen(false)}
      />
    </div>
  );
}
