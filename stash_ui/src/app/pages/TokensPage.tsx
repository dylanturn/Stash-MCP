import React from 'react';
import { TokensManager } from '../components/TokensManager';

export function TokensPage() {
  return (
    <div
      className="min-h-screen w-screen p-8"
      style={{
        backgroundColor: 'var(--stash-bg-base)',
        color: 'var(--stash-text-primary)',
      }}
    >
      <div className="max-w-4xl mx-auto">
        <div className="flex justify-end mb-6">
          <a
            href="/ui"
            className="px-3 py-2 rounded-md border text-sm"
            style={{
              borderColor: 'var(--stash-border)',
              color: 'var(--stash-text-secondary)',
            }}
          >
            Back to content
          </a>
        </div>
        <div
          className="p-6 rounded-md"
          style={{
            backgroundColor: 'var(--stash-bg-surface)',
            border: '1px solid var(--stash-border)',
          }}
        >
          <TokensManager />
        </div>
      </div>
    </div>
  );
}
