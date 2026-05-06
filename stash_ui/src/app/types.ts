export interface FileNode {
  id: string;
  name: string;
  type: 'file' | 'folder';
  path: string;
  extension?: string;
  children?: FileNode[];
  content?: string;
  size?: number;
  lastModified?: string;
  mimeType?: string;
}

export interface DocumentMetadata {
  path: string;
  size: number;
  mimeType: string;
  lastModified: string;
  characterCount: number;
  wordCount: number;
}

/** Shape returned by GET /api/tree */
export interface ApiTreeNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  children?: ApiTreeNode[];
}

/** Convert the root tree node from the API into the FileNode[] the UI expects. */
export function apiTreeToFileNodes(root: ApiTreeNode): FileNode[] {
  return (root.children ?? []).map(convertNode);
}

function convertNode(node: ApiTreeNode): FileNode {
  const extension =
    node.type === 'file' ? node.name.split('.').pop() : undefined;
  return {
    id: node.path || node.name,
    name: node.name,
    type: node.type === 'directory' ? 'folder' : 'file',
    path: node.path,
    extension,
    children: node.children?.map(convertNode),
  };
}
