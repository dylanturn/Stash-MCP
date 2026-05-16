import React from 'react';
import { useStore } from '../StoreContext';

// Minimal grouping: stores sort by (tenant_slug, slug) on the server, so
// we just walk the list and inject a label whenever the tenant changes.
export function StorePicker() {
  const { stores, current, setCurrent } = useStore();
  if (stores.length === 0) return null;

  return (
    <select
      value={current ? `${current.tenant_slug}/${current.slug}` : ''}
      onChange={(e) => {
        const [t, s] = e.target.value.split('/');
        if (t && s) setCurrent(t, s);
      }}
      className="px-2 py-1.5 rounded border text-sm"
      style={{
        backgroundColor: 'var(--stash-bg-surface)',
        borderColor: 'var(--stash-border)',
        color: 'var(--stash-text-primary)',
      }}
      title="Switch store"
    >
      {renderOptions(stores)}
    </select>
  );
}

function renderOptions(
  stores: ReturnType<typeof useStore>['stores']
): React.ReactNode {
  const nodes: React.ReactNode[] = [];
  let currentTenant: string | null = null;
  let groupChildren: React.ReactNode[] = [];

  function flush() {
    if (currentTenant !== null && groupChildren.length > 0) {
      nodes.push(
        <optgroup key={currentTenant} label={currentTenant}>
          {groupChildren}
        </optgroup>
      );
    }
  }

  for (const s of stores) {
    if (s.tenant_slug !== currentTenant) {
      flush();
      currentTenant = s.tenant_slug;
      groupChildren = [];
    }
    groupChildren.push(
      <option
        key={`${s.tenant_slug}/${s.slug}`}
        value={`${s.tenant_slug}/${s.slug}`}
      >
        {s.display_name} ({s.slug})
      </option>
    );
  }
  flush();
  return nodes;
}
