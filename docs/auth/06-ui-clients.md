# 06 — SPA + UI client wiring

## Goal

Make the React SPA in `stash_ui/` work end-to-end with the authenticated
backend that 02–05 deliver. Add a thin auth-aware fetch wrapper, scope
`API_BASE` to the current store, route `/:store/*` in the SPA, mint and
list API tokens from a settings page, and update docs/README/USAGE for
the new deployment shape.

This is the last spec in the chain. After it lands, a user can log in via
OIDC in their browser, pick a store, browse/edit content in the SPA, and
mint API tokens for their MCP clients — all without leaving the UI.

## Out of scope

- New SPA pages beyond what's needed for store-scoping and token
  management. The existing `DocumentsPage` is the only feature page; this
  spec doesn't add new features, just makes the existing one auth-aware
  and adds a settings/tokens page.
- SSR. Vite + react-router with `basename: '/ui'` stays.
- Replacing `stash_mcp/ui.py`. That stays as the fallback UI for now;
  removing it is a separate decision.

## Files added

```
stash_ui/src/api/fetch.ts            # auth-aware fetch wrapper
stash_ui/src/app/StoreContext.tsx    # provides current store slug + list
stash_ui/src/app/pages/LoginPage.tsx # not interactive — just renders "redirecting"
                                     # the actual redirect is at /auth/login server-side
stash_ui/src/app/pages/NoStoresPage.tsx
stash_ui/src/app/pages/TokensPage.tsx
stash_ui/src/app/components/StorePicker.tsx
stash_ui/src/app/hooks/useAuth.ts    # reads /auth/me, returns Principal-ish object
stash_ui/src/app/hooks/useStore.ts   # reads /api/admin/tenants/<t>/stores (or a scoped endpoint)
docs/deployment.md                   # new deployment guide
```

## Files modified

```
stash_ui/src/api/client.ts           # API_BASE becomes a function; calls go through fetch wrapper
stash_ui/src/app/App.tsx             # add StoreContext provider, /me probe
stash_ui/src/app/routes.tsx          # routes become /:store/*; add /account/tokens
stash_ui/src/app/pages/DocumentsPage.tsx  # reads store slug from useStore()
stash_mcp/auth/routes.py             # add GET /auth/me, GET /auth/stores (returns SPA-shaped principal + store list)
README.md                            # auth deployment section
USAGE.md                             # auth/store usage examples
```

`GET /auth/me` is technically backend work but it's trivial and only
exists to serve the SPA — bundling it here keeps the auth-routes spec
(05) focused on the redirect flow.

## Design

### Backend: `GET /auth/me`

Returns the current principal as JSON for the SPA to consume on startup.
Public path semantically (any authenticated caller), no store required —
add it to the resolver's `public_prefixes` allowlist.

```python
@router.get("/auth/me")
async def me():
    p = require_principal()
    return {
        "user_id": str(p.user_id),
        "email": p.email,
        "display_name": p.display_name,
        "auth_method": p.auth_method,
        "tenant_roles": {str(tid): r for tid, r in p.tenant_roles.items()},
    }

@router.get("/auth/stores")
async def my_stores():
    """Stores the current principal can access, across all their tenant memberships."""
    p = require_principal()
    # Query stores where tenant_id in p.tenant_roles.keys()
    ...
```

`/auth/me` and `/auth/stores` are how the SPA discovers what it can show
without needing the admin API.

### `stash_ui/src/api/fetch.ts`

```typescript
export interface StashFetchOptions extends RequestInit {
  // When true, a 401 will redirect to /auth/login instead of throwing.
  redirectOn401?: boolean;
}

export async function stashFetch(
  input: string,
  init: StashFetchOptions = {}
): Promise<Response> {
  const { redirectOn401 = true, ...rest } = init;
  const res = await fetch(input, {
    ...rest,
    credentials: 'same-origin',
  });
  if (res.status === 401 && redirectOn401) {
    const next = window.location.pathname + window.location.search;
    window.location.assign(`/auth/login?next=${encodeURIComponent(next)}`);
    // Throw so callers don't try to read body — the page is about to unload.
    throw new Error('redirecting to login');
  }
  if (res.status === 403) {
    // Surface to caller — typically the UI shows a "no access" banner.
    throw new HttpError(403, 'forbidden');
  }
  return res;
}

export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}
```

Every API call in `client.ts` switches from `fetch(...)` to
`stashFetch(...)`. The change is mechanical.

### Handling ETag and 412

The per-store content endpoints from spec 04 return `ETag` on reads and
respect `If-Match` on writes. The SPA's editor needs to thread the ETag
through.

**Read path.** When `getContent(store, path)` fetches a file, the wrapper
captures the response ETag and returns it alongside the body:

```typescript
export async function getContent(store: string, path: string) {
  const res = await stashFetch(`${apiBase(store)}/content/${path}`);
  if (!res.ok) throw new Error(`Failed to get content: ${res.statusText}`);
  return { content: await res.json(), etag: res.headers.get('ETag') };
}
```

`DocumentsPage` keeps `etag` in component state alongside the loaded
content.

**Write path.** When `putContent` saves, it sends `If-Match`:

```typescript
export async function putContent(store: string, path: string, content: string, etag: string | null) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (etag) headers['If-Match'] = etag;
  const res = await stashFetch(`${apiBase(store)}/content/${path}`, {
    method: 'PUT', headers, body: JSON.stringify({ content }),
  });
  if (res.status === 412) {
    const problem = await res.json();  // Problem Details body
    throw new ConcurrentEditError(problem.current_etag);
  }
  if (!res.ok) throw new Error(`Failed to save: ${res.statusText}`);
  return { etag: res.headers.get('ETag') };
}
```

`ConcurrentEditError` is a typed Error the editor catches to render a
"someone else modified this file" dialog with options: discard local
changes (reload), overwrite (send PUT with no If-Match), or open a diff
view. v1 ships discard + overwrite; diff view is a follow-on.

**304 handling.** `fetch()` does *not* automatically use `If-None-Match`
unless caching is configured. For v1, **don't** implement an in-SPA
cache that sets `If-None-Match` on subsequent reads — the win is small
(DocumentsPage rereads are rare enough) and the cache invalidation logic
adds real complexity. Browsers do reuse responses with `Cache-Control`
headers, but Stash content endpoints don't set those today. Track as a
follow-on optimization: add `Cache-Control: private, must-revalidate` on
GET responses, set `If-None-Match` on the SPA side.

### Problem Details on 4xx/5xx

The new endpoints return `application/problem+json` bodies. The fetch
wrapper grows a small helper to parse them:

```typescript
export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  [extra: string]: unknown;
}

export class ProblemError extends Error {
  constructor(public problem: Problem) {
    super(problem.detail ?? problem.title);
  }
}

// Inside stashFetch:
if (!res.ok && res.headers.get('Content-Type')?.startsWith('application/problem+json')) {
  const problem = await res.json();
  throw new ProblemError(problem);
}
```

Components catch `ProblemError` to render meaningful UI (`problem.type`
discriminates), and fall back to a generic error toast for non-typed
failures. `ConcurrentEditError` above is a thin subclass of
`ProblemError` for the 412 case.

### `stash_ui/src/api/client.ts` changes

```typescript
import { stashFetch } from './fetch';

function apiBase(store: string): string {
  return `/api/${store}`;
}

export async function getTree(store: string) {
  const res = await stashFetch(`${apiBase(store)}/tree`);
  if (!res.ok) throw new Error(`Failed to get tree: ${res.statusText}`);
  return res.json();
}

// ... same pattern for all other calls. Every signature takes `store` as
// the first arg.
```

A wrapper that closes over `store` is cleaner for callers:

```typescript
export function createApiClient(store: string) {
  return {
    getTree: () => getTree(store),
    listContent: (path = '') => listContent(store, path),
    // ...
  };
}
```

`StoreContext` provides this client to the rest of the app.

### `StoreContext.tsx`

```typescript
import { createContext, useContext, useEffect, useState } from 'react';
import { stashFetch } from '../api/fetch';

interface Store { id: string; slug: string; display_name: string; tenant_slug: string; }

interface StoreContextValue {
  stores: Store[];
  current: Store | null;
  setCurrent: (slug: string) => void;
  loading: boolean;
}

const StoreCtx = createContext<StoreContextValue | null>(null);

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [stores, setStores] = useState<Store[]>([]);
  const [current, setCurrentState] = useState<Store | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    stashFetch('/auth/stores')
      .then(r => r.json())
      .then((data: Store[]) => {
        setStores(data);
        // Pick from URL path first, else first store
        const fromUrl = window.location.pathname.split('/')[2]; // /ui/<store>/...
        const picked = data.find(s => s.slug === fromUrl) ?? data[0] ?? null;
        setCurrentState(picked);
        setLoading(false);
      });
  }, []);

  function setCurrent(slug: string) {
    const s = stores.find(x => x.slug === slug);
    if (s) {
      setCurrentState(s);
      // Update URL without full reload
      const newPath = window.location.pathname.replace(/^\/ui\/[^/]+/, `/ui/${slug}`);
      window.history.replaceState(null, '', newPath);
    }
  }

  return (
    <StoreCtx.Provider value={{ stores, current, setCurrent, loading }}>
      {children}
    </StoreCtx.Provider>
  );
}

export function useStore() {
  const ctx = useContext(StoreCtx);
  if (!ctx) throw new Error('useStore must be inside StoreProvider');
  return ctx;
}
```

### `routes.tsx`

```typescript
import { createBrowserRouter, Navigate } from 'react-router';
import { DocumentsPage } from './pages/DocumentsPage';
import { TokensPage } from './pages/TokensPage';
import { NoStoresPage } from './pages/NoStoresPage';

export const router = createBrowserRouter(
  [
    { path: '/', element: <RootRedirect /> },
    { path: '/account/tokens', Component: TokensPage },
    { path: '/no-stores', Component: NoStoresPage },
    { path: '/:store/*', Component: DocumentsPage },
  ],
  { basename: '/ui' }
);

function RootRedirect() {
  const { stores, loading } = useStore();
  if (loading) return null;
  if (stores.length === 0) return <Navigate to="/no-stores" replace />;
  return <Navigate to={`/${stores[0].slug}`} replace />;
}
```

### `App.tsx`

Wraps everything in `<StoreProvider>` and a `<UserProvider>` (or
`useAuth` hook). On mount, hits `/auth/me` to populate the user
context; if that returns 401, the fetch wrapper takes over and
redirects.

### `TokensPage.tsx`

Tabular view of the user's tokens (name, scopes, expires_at, last_used_at,
revoked status). Buttons:

- "New token" opens a dialog (Radix `Dialog` — already in the SPA's
  dependency list). Form: name, scopes (checkboxes for read/write),
  expires_in_days (number input). On submit, POST `/auth/tokens`. The
  response's `token` field is displayed once in a copyable code block
  with a strong warning that it won't be shown again.
- "Revoke" on each row → DELETE `/auth/tokens/:id` after a confirm dialog.

### `useAuth.ts`

```typescript
export function useAuth() {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    stashFetch('/auth/me')
      .then(r => r.json())
      .then(data => { setMe(data); setLoading(false); });
  }, []);
  return { me, loading };
}
```

Simple, no global state lib. The component using it re-renders on the
`me` update. Sign-out is just `<a href="/auth/logout">`.

### Auth-disabled mode

When the backend is in auth-disabled mode, `/auth/me` won't exist.
The SPA's startup probe gets a 404. Handle this: if `/auth/me` returns
404, treat it as "auth disabled" and skip the store-scoping (use the
legacy `/api/*` paths). The fetch wrapper can detect this on the first
call and set a global flag.

Honestly the simpler answer: **the SPA only supports auth-enabled
backends**. Auth-disabled deployments use the server-rendered
`stash_mcp/ui.py` instead. This is consistent with the rest of the
"don't mix layouts" posture. Document it; don't try to make the SPA
work in both modes.

### Documentation updates

`README.md`:
- New "Running with auth" section near the top of the install/run docs.
  Points at `docs/auth/README.md` for the design rationale and
  `docs/deployment.md` for ops.
- The existing "Best Practices" mention of "run behind a reverse proxy"
  is updated: with auth enabled, the reverse proxy is no longer required
  for security, only for TLS termination and rate limiting.

`USAGE.md`:
- Add a section on configuring an MCP client to use a store with an API
  token. Example: `Authorization: Bearer stash_pat_...` and URL
  `https://stash.example.com/mcp/docs/`.
- Add a section on tenant/store/membership management via CLI.

`docs/deployment.md` (new):
- The two layouts (auth-enabled, auth-disabled) and how to choose.
- Required env vars in each mode (with a table).
- Postgres setup pointer.
- dex-as-dev-IdP walkthrough.
- The "no migration" warning, repeated for emphasis.

## Test plan

Frontend tests are not currently set up in this repo (no `vitest`/`jest`
config in the SPA's package.json). **Don't add a test framework as part
of this chunk** — that's its own initiative. Acceptance is manual
end-to-end.

Backend bit:
- `tests/admin/test_oidc_routes.py` extended:
  - `/auth/me` returns expected shape.
  - `/auth/stores` returns only stores the principal can access.

## Acceptance

- Manual flow (see 05's acceptance, with one addition): after logging in,
  visit `/ui` → redirected to `/ui/<first-store>` → DocumentsPage renders
  with that store's files.
- Switch store via the picker → URL updates, files refresh.
- Mint a token at `/ui/account/tokens` → use it from an MCP client
  configured with `https://host/mcp/<store>/` → reads and writes work.
- Sign out → cookie cleared, next `/ui` visit redirects to `/auth/login`.
- All existing SPA functionality (DocumentsPage tree, edit, save) still
  works.

## Open questions

**Should the SPA replace `stash_mcp/ui.py` after this lands?** Not in this
chunk, but worth scheduling. Once the SPA covers the same surface
(content browsing + editing) and the auth flow is proven, deleting
`ui.py` reduces maintenance. The deletion is mechanical — drop the
router include and the file. Track as a follow-on issue.

**Service-worker / refresh-token handling.** Session cookies are 12h.
After they expire, the next API call gets a 401 and the SPA bounces to
re-login. No refresh token flow in v1 — keep it simple. If the UX of
"silent re-login when the cookie expires" matters, that's a follow-on.

## Notes for the Claude Code session

- The fetch wrapper's redirect behavior is deliberately disruptive — it
  unloads the page. Don't try to make every component handle 401
  gracefully; the wrapper centralizes the response.
- `credentials: 'same-origin'` is the default for `fetch`, but make it
  explicit so anyone reading the code sees it's intentional.
- Don't add `axios` or another HTTP library. `fetch` is fine; the wrapper
  is 20 lines.
- `/auth/me`, `/auth/stores`, `/auth/tokens` are all mounted on the
  same `/auth` router from spec 05. They're JSON APIs, not browser
  redirects, but keeping everything auth-related under `/auth/*` keeps
  the prefix tree clean. The store resolver from spec 04 already
  allowlists `/auth` and `/api/health`, so no change there.
