import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { getMe, getMyStores, Me, StoreSummary } from '../api/auth';
import { ApiClient, createApiClient } from '../api/client';
import { HttpError } from '../api/fetch';

interface StoreContextValue {
  stores: StoreSummary[];
  current: StoreSummary | null;
  me: Me | null;
  loading: boolean;
  // Populated when /auth/stores returned a non-404 failure. Distinct from
  // `stores.length === 0` (which means "authed but no memberships") and
  // from `authDisabled` (which means "this backend has no /auth/* router").
  error: string | null;
  // `/auth/stores` returned 404, i.e. the backend was built without auth.
  // The SPA is only supported on auth-enabled deployments — render a
  // clear message instead of falling into the /no-stores flow.
  authDisabled: boolean;
  setCurrent: (tenantSlug: string, storeSlug: string) => void;
  refreshStores: () => Promise<void>;
  client: ApiClient | null;
}

const StoreCtx = createContext<StoreContextValue | null>(null);

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [current, setCurrentState] = useState<StoreSummary | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [authDisabled, setAuthDisabled] = useState(false);
  const navigate = useNavigate();
  const params = useParams();

  useEffect(() => {
    let cancelled = false;
    // Load identity and store memberships in parallel. Both are gated
    // behind the same auth router on the backend; a 404 on either means
    // the deployment is running without auth.
    Promise.all([getMe(), getMyStores()])
      .then(([meData, data]) => {
        if (cancelled) return;
        setMe(meData);
        setStores(data);
        const tenantFromUrl = params.tenant;
        const storeFromUrl = params.store;
        const picked =
          data.find(
            (s) =>
              s.tenant_slug === tenantFromUrl && s.slug === storeFromUrl
          ) ?? null;
        setCurrentState(picked);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof HttpError && err.status === 404) {
          setAuthDisabled(true);
        } else {
          setError(err instanceof Error ? err.message : String(err));
        }
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Only run once on mount — URL changes are handled by the syncing
    // effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep `current` in sync with the URL when the user navigates via the
  // store picker or browser nav. The picker calls `setCurrent` which in
  // turn `navigate()`s, then this effect picks up the new params.
  //
  // If the URL points at a store the user doesn't have — directly typed,
  // bookmarked, or revoked since their last visit — null out `current`
  // so consumers can render their own redirect/empty state instead of
  // continuing to operate on the previously-selected store.
  useEffect(() => {
    if (stores.length === 0) return;
    if (!params.tenant || !params.store) return;
    const match = stores.find(
      (s) => s.tenant_slug === params.tenant && s.slug === params.store
    );
    if (match) {
      if (match !== current) setCurrentState(match);
    } else if (current !== null) {
      setCurrentState(null);
    }
  }, [params.tenant, params.store, stores, current]);

  function setCurrent(tenantSlug: string, storeSlug: string) {
    const s = stores.find(
      (x) => x.tenant_slug === tenantSlug && x.slug === storeSlug
    );
    if (!s) return;
    setCurrentState(s);
    navigate(`/${tenantSlug}/${storeSlug}`);
  }

  async function refreshStores() {
    const data = await getMyStores();
    setStores(data);
  }

  const client = useMemo<ApiClient | null>(
    () =>
      current ? createApiClient(current.tenant_slug, current.slug) : null,
    [current]
  );

  return (
    <StoreCtx.Provider
      value={{ stores, current, me, loading, error, authDisabled, setCurrent, refreshStores, client }}
    >
      {children}
    </StoreCtx.Provider>
  );
}

export function useStore(): StoreContextValue {
  const ctx = useContext(StoreCtx);
  if (!ctx) throw new Error('useStore must be used inside <StoreProvider>');
  return ctx;
}

export function useApiClient(): ApiClient {
  const { client } = useStore();
  if (!client) {
    throw new Error(
      'useApiClient called with no active store — render guard missing'
    );
  }
  return client;
}
