import React from 'react';
import { createBrowserRouter, Navigate, Outlet } from 'react-router';
import { DocumentsPage } from './pages/DocumentsPage';
import { LoginPage } from './pages/LoginPage';
import { NoStoresPage } from './pages/NoStoresPage';
import { TokensPage } from './pages/TokensPage';
import { StoreProvider, useStore } from './StoreContext';

function StoreShell() {
  // Mount StoreProvider once for the whole SPA. Lives under the router
  // so the provider can read URL params via `useParams`.
  return (
    <StoreProvider>
      <Outlet />
    </StoreProvider>
  );
}

function RootRedirect() {
  const { stores, loading } = useStore();
  if (loading) return null;
  if (stores.length === 0) return <Navigate to="/no-stores" replace />;
  const first = stores[0];
  return <Navigate to={`/${first.tenant_slug}/${first.slug}`} replace />;
}

export const router = createBrowserRouter(
  [
    {
      element: <StoreShell />,
      children: [
        { path: '/', element: <RootRedirect /> },
        { path: 'login', Component: LoginPage },
        { path: 'no-stores', Component: NoStoresPage },
        { path: 'account/tokens', Component: TokensPage },
        { path: ':tenant/:store', Component: DocumentsPage },
        { path: ':tenant/:store/*', Component: DocumentsPage },
      ],
    },
  ],
  { basename: '/ui' }
);
