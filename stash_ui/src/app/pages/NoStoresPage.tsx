import React from 'react';

export function NoStoresPage() {
  return (
    <div
      className="h-screen w-screen flex items-center justify-center"
      style={{ backgroundColor: 'var(--stash-bg-base)' }}
    >
      <div
        className="max-w-lg p-8 rounded border text-center"
        style={{
          backgroundColor: 'var(--stash-bg-surface)',
          borderColor: 'var(--stash-border)',
          color: 'var(--stash-text-primary)',
        }}
      >
        <h1 className="text-2xl mb-3">No stores available</h1>
        <p
          className="mb-6"
          style={{ color: 'var(--stash-text-secondary)' }}
        >
          Your account is signed in, but you don't have access to any stores
          yet. Ask an administrator to add you to a tenant, or to provision a
          store under one you already belong to.
        </p>
        <a
          href="/auth/logout"
          className="inline-block px-4 py-2 rounded border"
          style={{
            borderColor: 'var(--stash-border)',
            color: 'var(--stash-text-primary)',
          }}
        >
          Sign out
        </a>
      </div>
    </div>
  );
}
