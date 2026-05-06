import React, { useEffect } from 'react';
import { RouterProvider } from 'react-router';
import { router } from './routes';
import { Toaster } from 'sonner';
import { THEMES, applyTheme } from './components/AppearanceSettings';

export default function App() {
  useEffect(() => {
    const savedId = localStorage.getItem('stash-theme') ?? 'teal';
    const theme = THEMES.find((t) => t.id === savedId) ?? THEMES[0];
    applyTheme(theme);
  }, []);

  return (
    <>
      <Toaster
        position="top-right"
        toastOptions={{
          style: {
            background: 'var(--stash-bg-elevated)',
            color: 'var(--stash-text-primary)',
            border: '1px solid var(--stash-border)',
          },
        }}
      />
      <RouterProvider router={router} />
    </>
  );
}