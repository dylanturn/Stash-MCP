import React, { useEffect } from 'react';

// Reached only when client-side code lands the user on `/login` without
// going through the backend redirect — bounce them through `/auth/login`
// so the OIDC dance starts.
export function LoginPage() {
  useEffect(() => {
    const next = '/ui';
    window.location.assign(`/auth/login?next=${encodeURIComponent(next)}`);
  }, []);
  return (
    <div
      className="h-screen w-screen flex items-center justify-center"
      style={{
        backgroundColor: 'var(--stash-bg-base)',
        color: 'var(--stash-text-secondary)',
      }}
    >
      Redirecting to login…
    </div>
  );
}
