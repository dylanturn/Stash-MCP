import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Navigate } from 'react-router';
import { FileNode, apiTreeToFileNodes } from '../types';
import { ConcurrentEditError } from '../../api/fetch';
import { useStore } from '../StoreContext';
import { FileTree } from '../components/FileTree';
import { DocumentViewer } from '../components/DocumentViewer';
import { DirectoryListing } from '../components/DirectoryListing';
import { MetadataPanel } from '../components/MetadataPanel';
import { OverviewContent } from '../components/OverviewContent';
import { NewDocumentModal } from '../components/NewDocumentModal';
import { OrganizationSettingsModal } from '../components/OrganizationSettingsModal';
import { UserSettingsModal } from '../components/UserSettingsModal';
import { Heading } from '../components/TableOfContents';
import { Endpoint } from '../components/EndpointsList';
import { Section } from '../components/SectionsList';
import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
import { GitBranchInfo } from '../mockData/gitChanges';

export function DocumentsPage() {
  const {
    stores,
    current,
    me,
    loading: storeLoading,
    error: storeError,
    authDisabled,
    client,
  } = useStore();
  const isTenantAdmin = current?.role === 'admin';
  // The latest client. Async fetches capture this at call time so they
  // can detect that they're stale (the user switched stores while the
  // request was in flight) and drop their result instead of stomping the
  // newly-loaded store's state.
  const clientRef = useRef(client);
  useEffect(() => {
    clientRef.current = client;
  });
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<FileNode | null>(null);
  const [selectedEtag, setSelectedEtag] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isContentLoading, setIsContentLoading] = useState(false);
  const [isLeftPanelOpen, setIsLeftPanelOpen] = useState(true);
  const [isRightPanelOpen, setIsRightPanelOpen] = useState(true);
  const [isNewDocModalOpen, setIsNewDocModalOpen] = useState(false);
  const [isUserSettingsOpen, setIsUserSettingsOpen] = useState(false);
  const [isOrgSettingsOpen, setIsOrgSettingsOpen] = useState(false);
  const [headings, setHeadings] = useState<Heading[]>([]);
  const [activeHeadingId, setActiveHeadingId] = useState<string | null>(null);
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [activeEndpointId, setActiveEndpointId] = useState<string | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const [sectionsTitle, setSectionsTitle] = useState<string>('Sections');
  const [gitInfo, setGitInfo] = useState<GitBranchInfo | null>(null);

  // Fetch the file tree from the API. Bound to the currently-selected
  // store via the API client returned from `useStore`. Captures the
  // active client at call time and drops the result if the user
  // switched stores while the request was in flight.
  const refreshTree = useCallback(async () => {
    if (!client) return;
    const reqClient = client;
    try {
      const tree = await reqClient.getTree();
      if (clientRef.current !== reqClient) return;
      setFileTree(apiTreeToFileNodes(tree));
    } catch (err) {
      if (clientRef.current !== reqClient) return;
      console.error('Failed to load file tree:', err);
      toast.error('Failed to load file tree');
    } finally {
      if (clientRef.current === reqClient) setIsLoading(false);
    }
  }, [client]);

  // Reload tree + git overview whenever the active store changes. Also
  // clears any selection from the previous store so the editor doesn't
  // hold a stale ETag.
  useEffect(() => {
    if (!client) return;
    const reqClient = client;
    setIsLoading(true);
    setSelectedFile(null);
    setSelectedEtag(null);
    refreshTree();
    reqClient.getGitOverview().then((data) => {
      if (clientRef.current !== reqClient) return;
      if (data) setGitInfo(data as GitBranchInfo);
      else setGitInfo(null);
    });
  }, [client, refreshTree]);

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

  // Identifies the latest file-load request. Async fetches compare this
  // against their own request id when they resolve so a slow load doesn't
  // overwrite a newer selection's content.
  const latestSelectionRef = useRef(0);

  // Load file content from the API when a file is selected
  const handleSelectFile = useCallback(async (file: FileNode) => {
    if (file.type === 'folder') {
      latestSelectionRef.current += 1;
      setSelectedFile(file);
      setSelectedEtag(null);
      // Owning the loading flag: bumping the ref invalidates any
      // in-flight uncached load, whose `finally` will now no-op. Clear
      // here so the spinner doesn't get stuck on top of the folder view.
      setIsContentLoading(false);
      return;
    }

    // Cache hit: the FileNode carries its own content + ETag from a
    // prior load. Use both — using the globally-tracked `selectedEtag`
    // here would risk sending the previously-loaded file's ETag on the
    // next save (false 412).
    if (file.content !== undefined && file.etag) {
      latestSelectionRef.current += 1;
      setSelectedFile(file);
      setSelectedEtag(file.etag);
      // Same reason as the folder branch — clear in case an earlier
      // uncached load set the spinner and is now invalidated.
      setIsContentLoading(false);
      return;
    }

    if (!client) return;
    const reqClient = client;
    const reqId = ++latestSelectionRef.current;
    setIsContentLoading(true);
    setSelectedFile(file);
    setSelectedEtag(null);

    try {
      const { content: data, etag } = await reqClient.getContent(file.path);
      // Drop the result if the user switched stores or files while the
      // request was in flight.
      if (clientRef.current !== reqClient || latestSelectionRef.current !== reqId) {
        return;
      }
      const enrichedFile: FileNode = {
        ...file,
        content: data.content ?? '',
        size: data.content ? new TextEncoder().encode(data.content).length : 0,
        lastModified: data.updated_at ?? undefined,
        mimeType: data.mime_type ?? undefined,
        etag: etag ?? undefined,
      };
      setSelectedFile(enrichedFile);
      setSelectedEtag(etag);
      // Also update the file in the tree so re-selecting doesn't re-fetch.
      setFileTree((prev) => updateFileInTree(prev, file.id, enrichedFile));
    } catch (err) {
      if (clientRef.current !== reqClient || latestSelectionRef.current !== reqId) {
        return;
      }
      console.error('Failed to load file content:', err);
      toast.error('Failed to load file content');
    } finally {
      if (clientRef.current === reqClient && latestSelectionRef.current === reqId) {
        setIsContentLoading(false);
      }
    }
  }, [client]);

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
    if (!selectedFile || !client) return;

    try {
      const { etag } = await client.putContent(
        selectedFile.path,
        content,
        selectedEtag
      );
      const updatedFile: FileNode = {
        ...selectedFile,
        content,
        size: new TextEncoder().encode(content).length,
        lastModified: new Date().toISOString(),
        etag: etag ?? undefined,
      };
      setSelectedFile(updatedFile);
      setSelectedEtag(etag);
      setFileTree((prev) => updateFileInTree(prev, selectedFile.id, updatedFile));
      toast.success('Document saved');
    } catch (err) {
      if (err instanceof ConcurrentEditError) {
        // Reload server copy so the user sees what's there now; the
        // editor's unsaved buffer is lost. v1 ships discard only; a
        // diff/overwrite affordance is a follow-on (spec 06).
        toast.error(
          'Another writer changed this file. Reloaded the latest version.'
        );
        const path = selectedFile.path;
        try {
          const { content: data, etag } = await client.getContent(path);
          const reloaded: FileNode = {
            ...selectedFile,
            content: data.content ?? '',
            size: data.content
              ? new TextEncoder().encode(data.content).length
              : 0,
            lastModified: data.updated_at ?? undefined,
            mimeType: data.mime_type ?? undefined,
            etag: etag ?? undefined,
          };
          setSelectedFile(reloaded);
          setSelectedEtag(etag);
          setFileTree((prev) =>
            updateFileInTree(prev, selectedFile.id, reloaded)
          );
        } catch (reloadErr) {
          console.error('Failed to reload after 412:', reloadErr);
        }
        return;
      }
      console.error('Failed to save file:', err);
      toast.error('Failed to save document');
    }
  };

  const handleDeleteFile = async () => {
    if (!selectedFile || !client) return;

    try {
      await client.deleteContent(selectedFile.path);
      setSelectedFile(null);
      setSelectedEtag(null);
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
    if (!client) return;
    const destination = window.prompt(`Move "${item.name}" to (new path):`, item.path);
    if (!destination || destination === item.path) return;

    try {
      await client.moveContent(item.path, destination);
      await refreshTree();
      toast.success(`Moved to ${destination}`);
    } catch (err) {
      console.error('Failed to move item:', err);
      toast.error('Failed to move item');
    }
  };

  const handleDeleteItemFromListing = async (item: FileNode) => {
    if (!client) return;
    const itemType = item.type === 'folder' ? 'directory' : 'file';
    const confirmed = window.confirm(`Are you sure you want to delete ${itemType} "${item.name}"?`);
    if (!confirmed) return;

    try {
      await client.deleteContent(item.path);
      if (selectedFile?.id === item.id) {
        setSelectedFile(null);
        setSelectedEtag(null);
      }
      await refreshTree();
      toast.success(`${item.type === 'folder' ? 'Directory' : 'File'} deleted`);
    } catch (err) {
      console.error('Failed to delete item:', err);
      toast.error('Failed to delete item');
    }
  };

  const handleCreateDocument = async (path: string, content: string, _template: string) => {
    if (!client) return;
    try {
      const { etag } = await client.createContent(path, content);
      await refreshTree();

      // Select the newly created file. Capturing the create ETag here is
      // load-bearing — without it the next save would send whatever ETag
      // happened to be in `selectedEtag` from the previous selection.
      const newFile: FileNode = {
        id: path,
        name: path.split('/').pop() || 'untitled',
        type: 'file',
        path,
        extension: path.split('.').pop(),
        content,
        size: new TextEncoder().encode(content).length,
        lastModified: new Date().toISOString(),
        etag: etag ?? undefined,
      };
      latestSelectionRef.current += 1;
      setSelectedFile(newFile);
      setSelectedEtag(etag);
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

  if (storeLoading) {
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
            Loading stores...
          </span>
        </div>
      </div>
    );
  }

  // The URL pointed at a tenant/store the user can't see (or that
  // doesn't exist for them). Bounce: no stores → /no-stores; otherwise
  // land them on the first one they do have. Auth-disabled and outright
  // errors render their own state at the root route, but we surface them
  // here too in case the user deep-linked.
  if (!current) {
    if (authDisabled) {
      return <Navigate to="/" replace />;
    }
    if (storeError) {
      return <Navigate to="/" replace />;
    }
    if (stores.length === 0) return <Navigate to="/no-stores" replace />;
    const first = stores[0];
    return (
      <Navigate to={`/${first.tenant_slug}/${first.slug}`} replace />
    );
  }

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
                onOpenSettings={() => setIsUserSettingsOpen(true)}
                onOpenOrgSettings={
                  isTenantAdmin ? () => setIsOrgSettingsOpen(true) : undefined
                }
                onMoveItem={handleMoveItem}
                onDeleteItem={handleDeleteItemFromListing}
                gitInfo={gitInfo ?? undefined}
                userName={me?.display_name ?? me?.email ?? 'Signed in'}
                userEmail={me?.email ?? ''}
                isTenantAdmin={isTenantAdmin}
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

      {/* User (Account) Settings Modal */}
      {me && (
        <UserSettingsModal
          isOpen={isUserSettingsOpen}
          onClose={() => setIsUserSettingsOpen(false)}
          me={me}
          stores={stores}
        />
      )}

      {/* Organization Settings Modal — admins only. The badge dropdown
          gates the entry point, but guard here too in case the modal
          state is forced open through some other path. */}
      {isTenantAdmin && (
        <OrganizationSettingsModal
          isOpen={isOrgSettingsOpen}
          onClose={() => setIsOrgSettingsOpen(false)}
        />
      )}
    </div>
  );
}
