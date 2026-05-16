import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { getMyStores, StoreSummary } from '../api/auth';
import { ApiClient, createApiClient } from '../api/client';

interface StoreContextValue {
  stores: StoreSummary[];
  current: StoreSummary | null;
  loading: boolean;
  error: string | null;
  setCurrent: (tenantSlug: string, storeSlug: string) => void;
  client: ApiClient | null;
}

const StoreCtx = createContext<StoreContextValue | null>(null);

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [current, setCurrentState] = useState<StoreSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const params = useParams();

  useEffect(() => {
    let cancelled = false;
    getMyStores()
      .then((data) => {
        if (cancelled) return;
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
        setError(err instanceof Error ? err.message : String(err));
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
  useEffect(() => {
    if (stores.length === 0) return;
    const match = stores.find(
      (s) => s.tenant_slug === params.tenant && s.slug === params.store
    );
    if (match && match !== current) setCurrentState(match);
  }, [params.tenant, params.store, stores, current]);

  function setCurrent(tenantSlug: string, storeSlug: string) {
    const s = stores.find(
      (x) => x.tenant_slug === tenantSlug && x.slug === storeSlug
    );
    if (!s) return;
    setCurrentState(s);
    navigate(`/${tenantSlug}/${storeSlug}`);
  }

  const client = useMemo<ApiClient | null>(
    () =>
      current ? createApiClient(current.tenant_slug, current.slug) : null,
    [current]
  );

  return (
    <StoreCtx.Provider
      value={{ stores, current, loading, error, setCurrent, client }}
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
