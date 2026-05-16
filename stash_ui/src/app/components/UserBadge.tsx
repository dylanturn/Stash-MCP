import React, { useState, useRef, useEffect } from 'react';
import { Settings, Building2, LogOut, ChevronUp } from 'lucide-react';

interface UserBadgeProps {
  name: string;
  email: string;
  avatarUrl?: string;
  // Show the "Organization Settings" menu entry. Reserved for tenant
  // admins so non-admins don't see (or attempt to use) controls they
  // can't apply.
  showOrgSettings?: boolean;
  onOpenSettings?: () => void;
  onOpenOrgSettings?: () => void;
}

export function UserBadge({
  name,
  email,
  avatarUrl,
  showOrgSettings = false,
  onOpenSettings,
  onOpenOrgSettings,
}: UserBadgeProps) {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsMenuOpen(false);
      }
    };

    if (isMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isMenuOpen]);

  const handleMenuAction = (action: string) => {
    setIsMenuOpen(false);
    if (action === 'settings') {
      onOpenSettings?.();
    } else if (action === 'org-settings') {
      onOpenOrgSettings?.();
    } else if (action === 'logout') {
      window.location.href = '/auth/logout';
    }
  };

  // Get initials from name for avatar fallback
  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map(part => part[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  };

  return (
    <div
      className="relative"
      ref={menuRef}
      style={{
        borderTop: '1px solid var(--stash-border)',
        backgroundColor: 'var(--stash-bg-base)',
      }}
    >
      {/* Dropdown Menu */}
      {isMenuOpen && (
        <div
          className="absolute bottom-full left-0 right-0 mb-1 rounded-md shadow-lg overflow-hidden"
          style={{
            backgroundColor: 'var(--stash-bg-elevated)',
            border: '1px solid var(--stash-border)',
          }}
        >
          <button
            onClick={() => handleMenuAction('settings')}
            className="w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-all duration-150"
            style={{
              backgroundColor: 'transparent',
              color: 'var(--stash-text-primary)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <Settings className="w-4 h-4" />
            <span>Account Settings</span>
          </button>
          {showOrgSettings && (
            <button
              onClick={() => handleMenuAction('org-settings')}
              className="w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-all duration-150"
              style={{
                backgroundColor: 'transparent',
                color: 'var(--stash-text-primary)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent';
              }}
            >
              <Building2 className="w-4 h-4" />
              <span>Organization Settings</span>
            </button>
          )}
          <div style={{ height: '1px', backgroundColor: 'var(--stash-border)' }} />
          <button
            onClick={() => handleMenuAction('logout')}
            className="w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-all duration-150"
            style={{
              backgroundColor: 'transparent',
              color: 'var(--stash-destructive)',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'rgba(243, 139, 168, 0.1)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <LogOut className="w-4 h-4" />
            <span>Sign Out</span>
          </button>
        </div>
      )}

      {/* User Badge Button */}
      <button
        onClick={() => setIsMenuOpen(!isMenuOpen)}
        className="w-full flex items-center gap-3 p-3 transition-all duration-150"
        style={{
          backgroundColor: isMenuOpen ? 'var(--stash-bg-hover)' : 'transparent',
          color: 'var(--stash-text-primary)',
        }}
        onMouseEnter={(e) => {
          if (!isMenuOpen) {
            e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
          }
        }}
        onMouseLeave={(e) => {
          if (!isMenuOpen) {
            e.currentTarget.style.backgroundColor = 'transparent';
          }
        }}
      >
        {/* Avatar */}
        <div
          className="flex items-center justify-center rounded-full flex-shrink-0"
          style={{
            width: '36px',
            height: '36px',
            backgroundColor: 'var(--stash-accent)',
            color: 'var(--stash-bg-base)',
            fontSize: '14px',
            fontWeight: '600',
          }}
        >
          {avatarUrl ? (
            <img
              src={avatarUrl}
              alt={name}
              className="w-full h-full rounded-full object-cover"
            />
          ) : (
            <span>{getInitials(name)}</span>
          )}
        </div>

        {/* User Info */}
        <div className="flex-1 text-left overflow-hidden">
          <div
            className="text-sm truncate"
            style={{ color: 'var(--stash-text-bright)' }}
          >
            {name}
          </div>
          <div
            className="text-xs truncate"
            style={{ color: 'var(--stash-text-secondary)' }}
          >
            {email}
          </div>
        </div>

        {/* Chevron */}
        <ChevronUp
          className="w-4 h-4 flex-shrink-0 transition-transform duration-150"
          style={{
            color: 'var(--stash-text-secondary)',
            transform: isMenuOpen ? 'rotate(0deg)' : 'rotate(180deg)',
          }}
        />
      </button>
    </div>
  );
}