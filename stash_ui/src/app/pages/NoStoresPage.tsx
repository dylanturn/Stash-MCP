import React, { useState } from 'react';
import { useNavigate } from 'react-router';
import { Plus } from 'lucide-react';
import { useStore } from '../StoreContext';
import { TenantMembership } from '../../api/auth';
import { CreateStoreModal } from '../components/CreateStoreModal';

export function NoStoresPage() {
  const { me, refreshStores } = useStore();
  const navigate = useNavigate();
  const [creatingIn, setCreatingIn] = useState<TenantMembership | null>(null);

  // Tenants where the user is an admin. They can self-provision the
  // first store via /tenants/{id}/stores instead of waiting on a global
  // admin to do it for them.
  const adminTenants = (me?.tenants ?? []).filter((t) => t.role === 'admin');

  return (
    <div
      className="h-screen w-screen flex items-center justify-center"
      style={{ backgroundColor: 'var(--stash-bg-base)' }}
    >
      <div
        className="max-w-lg w-full p-8 rounded border text-center"
        style={{
          backgroundColor: 'var(--stash-bg-surface)',
          borderColor: 'var(--stash-border)',
          color: 'var(--stash-text-primary)',
        }}
      >
        <h1 className="text-2xl mb-3">No stores available</h1>
        {adminTenants.length === 0 ? (
          <p
            className="mb-6"
            style={{ color: 'var(--stash-text-secondary)' }}
          >
            Your account is signed in, but you don't have access to any
            stores yet. Ask an administrator to add you to a tenant, or to
            provision a store under one you already belong to.
          </p>
        ) : (
          <>
            <p
              className="mb-6"
              style={{ color: 'var(--stash-text-secondary)' }}
            >
              You're an admin in{' '}
              {adminTenants.length === 1 ? 'this organization' : 'these organizations'}{' '}
              but haven't provisioned a store yet. Create one to get started.
            </p>
            <div
              className="rounded-md overflow-hidden mb-6"
              style={{ border: '1px solid var(--stash-border)' }}
            >
              {adminTenants.map((t, idx) => (
                <div
                  key={t.id}
                  className="flex items-center justify-between px-4 py-3 text-sm"
                  style={{
                    backgroundColor: 'var(--stash-bg-base)',
                    borderTop:
                      idx === 0 ? 'none' : '1px solid var(--stash-border)',
                  }}
                >
                  <div className="min-w-0 text-left">
                    <div style={{ color: 'var(--stash-text-bright)' }}>
                      {t.display_name}
                    </div>
                    <code
                      className="text-xs"
                      style={{ color: 'var(--stash-text-secondary)' }}
                    >
                      {t.slug}
                    </code>
                  </div>
                  <button
                    onClick={() => setCreatingIn(t)}
                    className="px-3 py-1.5 rounded-md text-sm inline-flex items-center gap-1 transition-all duration-150"
                    style={{
                      backgroundColor: 'var(--stash-accent)',
                      color: 'var(--stash-bg-base)',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.opacity = '0.9';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.opacity = '1';
                    }}
                  >
                    <Plus className="w-4 h-4" /> New store
                  </button>
                </div>
              ))}
            </div>
          </>
        )}
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

      {creatingIn && (
        <CreateStoreModal
          tenantId={creatingIn.id}
          tenantDisplayName={creatingIn.display_name}
          onClose={() => setCreatingIn(null)}
          onCreated={async (store) => {
            setCreatingIn(null);
            try {
              await refreshStores();
            } catch (err) {
              console.error(err);
            }
            navigate(`/${creatingIn.slug}/${store.slug}`);
          }}
        />
      )}
    </div>
  );
}
