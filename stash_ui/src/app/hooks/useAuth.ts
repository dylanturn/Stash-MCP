import { useEffect, useState } from 'react';
import { getMe, Me } from '../../api/auth';

export interface AuthState {
  me: Me | null;
  loading: boolean;
  error: string | null;
}

// Probes `/auth/me` on mount. A 401 response unloads the page via the
// fetch wrapper, so `error` only fires on genuine failures (5xx, network
// down). Other components downstream can assume `me` is the truthy
// principal once `loading` flips false.
export function useAuth(): AuthState {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((data) => {
        if (cancelled) return;
        setMe(data);
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
  }, []);

  return { me, loading, error };
}
