const API_BASE = '/api';

export async function getTree() {
  const res = await fetch(`${API_BASE}/tree`);
  if (!res.ok) throw new Error(`Failed to get tree: ${res.statusText}`);
  return res.json();
}

export async function listContent(path: string = '') {
  const res = await fetch(`${API_BASE}/content${path ? `/${path}` : ''}`);
  if (!res.ok) throw new Error(`Failed to list content: ${res.statusText}`);
  return res.json();
}

export async function getContent(path: string) {
  const res = await fetch(`${API_BASE}/content/${path}`);
  if (!res.ok) throw new Error(`Failed to get content: ${res.statusText}`);
  return res.json();
}

export async function createContent(path: string, content: string) {
  const res = await fetch(`${API_BASE}/content/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed to create content: ${res.statusText}`);
  return res.json();
}

export async function putContent(path: string, content: string) {
  const res = await fetch(`${API_BASE}/content/${path}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  });
  if (!res.ok) throw new Error(`Failed to update content: ${res.statusText}`);
  return res.json();
}

export async function deleteContent(path: string) {
  const res = await fetch(`${API_BASE}/content/${path}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`Failed to delete content: ${res.statusText}`);
  return res.json();
}

export async function moveContent(path: string, destination: string) {
  const res = await fetch(`${API_BASE}/content/${path}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ destination }),
  });
  if (!res.ok) throw new Error(`Failed to move content: ${res.statusText}`);
  return res.json();
}

export async function searchContent(query: string) {
  const res = await fetch(
    `${API_BASE}/search?q=${encodeURIComponent(query)}`
  );
  if (!res.ok) throw new Error(`Failed to search: ${res.statusText}`);
  return res.json();
}

export async function getSearchStatus() {
  const res = await fetch(`${API_BASE}/search/status`);
  if (!res.ok)
    throw new Error(`Failed to get search status: ${res.statusText}`);
  return res.json();
}

export async function getHealth() {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.statusText}`);
  return res.json();
}

export async function getGitOverview(): Promise<any | null> {
  try {
    const res = await fetch(`${API_BASE}/git/overview`);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}
