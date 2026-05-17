import React, { useState } from "react";
import { Check } from "lucide-react";

interface Theme {
  id: string;
  label: string;
  description: string;
  mode: "light" | "semi-dark" | "dark";
  vars: Record<string, string>;
}

interface ThemeGroup {
  label: string;
  mode: Theme["mode"];
  themes: Theme[];
}

export const THEMES: Theme[] = [
  // ── Light ────────────────────────────────────────────────────────────────
  {
    id: "latte",
    label: "Latte",
    description: "Warm off-white base with saturated teal accents",
    mode: "light",
    vars: {
      "--stash-bg-base": "#eff1f5",
      "--stash-bg-surface": "#e6e9ef",
      "--stash-bg-elevated": "#dce0e8",
      "--stash-bg-code": "#f5f5f7",
      "--stash-bg-hover": "#d2d6e0",
      "--stash-text-primary": "#4c4f69",
      "--stash-text-secondary": "#9ca0b0",
      "--stash-text-bright": "#1e2030",
      "--stash-accent": "#179299",
      "--stash-destructive": "#d20f39",
      "--stash-border": "#c8ccd8",
      "--stash-error": "#d20f39",
    },
  },
  {
    id: "breeze",
    label: "Breeze",
    description: "Cool blue-white surface with vivid sapphire accents",
    mode: "light",
    vars: {
      "--stash-bg-base": "#f0f4ff",
      "--stash-bg-surface": "#e4ecf8",
      "--stash-bg-elevated": "#d8e3f2",
      "--stash-bg-code": "#f8faff",
      "--stash-bg-hover": "#ccd8f0",
      "--stash-text-primary": "#3c4270",
      "--stash-text-secondary": "#808cb0",
      "--stash-text-bright": "#1e2248",
      "--stash-accent": "#1e66f5",
      "--stash-destructive": "#d20f39",
      "--stash-border": "#bccae8",
      "--stash-error": "#d20f39",
    },
  },
  {
    id: "parchment",
    label: "Parchment",
    description: "Warm sepia tones with rich amber-gold accents",
    mode: "light",
    vars: {
      "--stash-bg-base": "#f5efe0",
      "--stash-bg-surface": "#ede8d8",
      "--stash-bg-elevated": "#e4dece",
      "--stash-bg-code": "#faf7f0",
      "--stash-bg-hover": "#dcd4c0",
      "--stash-text-primary": "#48433a",
      "--stash-text-secondary": "#908878",
      "--stash-text-bright": "#28221a",
      "--stash-accent": "#8a7040",
      "--stash-destructive": "#b83232",
      "--stash-border": "#d4cbb8",
      "--stash-error": "#b83232",
    },
  },

  // ── Semi-Dark ─────────────────────────────────────────────────────────────
  {
    id: "teal",
    label: "Teal",
    description: "Warm-dark base with muted teal accents — the default",
    mode: "semi-dark",
    vars: {
      "--stash-bg-base": "#1e1e2e",
      "--stash-bg-surface": "#272738",
      "--stash-bg-elevated": "#2e2e42",
      "--stash-bg-code": "#181825",
      "--stash-bg-hover": "#353550",
      "--stash-text-primary": "#cdd6f4",
      "--stash-text-secondary": "#7f849c",
      "--stash-text-bright": "#e0e4f0",
      "--stash-accent": "#94e2d5",
      "--stash-destructive": "#f38ba8",
      "--stash-border": "#313244",
      "--stash-error": "#f38ba8",
    },
  },
  {
    id: "sapphire",
    label: "Sapphire",
    description: "Deep blue-navy base with cool sapphire accents",
    mode: "semi-dark",
    vars: {
      "--stash-bg-base": "#1a1b2e",
      "--stash-bg-surface": "#222440",
      "--stash-bg-elevated": "#2a2c4e",
      "--stash-bg-code": "#141528",
      "--stash-bg-hover": "#30335a",
      "--stash-text-primary": "#c8d0f0",
      "--stash-text-secondary": "#7078a0",
      "--stash-text-bright": "#dde4ff",
      "--stash-accent": "#89b4fa",
      "--stash-destructive": "#f38ba8",
      "--stash-border": "#2c2f52",
      "--stash-error": "#f38ba8",
    },
  },
  {
    id: "mauve",
    label: "Mauve",
    description: "Dark violet base with soft lavender accents",
    mode: "semi-dark",
    vars: {
      "--stash-bg-base": "#1e1a2e",
      "--stash-bg-surface": "#28223c",
      "--stash-bg-elevated": "#322a4a",
      "--stash-bg-code": "#16122a",
      "--stash-bg-hover": "#3c3258",
      "--stash-text-primary": "#d0c8f0",
      "--stash-text-secondary": "#8878a8",
      "--stash-text-bright": "#e8dcff",
      "--stash-accent": "#cba6f7",
      "--stash-destructive": "#f38ba8",
      "--stash-border": "#302848",
      "--stash-error": "#f38ba8",
    },
  },
  {
    id: "rose",
    label: "Rose",
    description: "Warm-dark base with rose-pink accents",
    mode: "semi-dark",
    vars: {
      "--stash-bg-base": "#221820",
      "--stash-bg-surface": "#2e2028",
      "--stash-bg-elevated": "#3a2832",
      "--stash-bg-code": "#1a1018",
      "--stash-bg-hover": "#44303e",
      "--stash-text-primary": "#f0d0d8",
      "--stash-text-secondary": "#a08090",
      "--stash-text-bright": "#ffe0e8",
      "--stash-accent": "#f38ba8",
      "--stash-destructive": "#fab387",
      "--stash-border": "#3a2830",
      "--stash-error": "#fab387",
    },
  },
  {
    id: "peach",
    label: "Peach",
    description: "Rich dark-brown base with warm peach accents",
    mode: "semi-dark",
    vars: {
      "--stash-bg-base": "#201c18",
      "--stash-bg-surface": "#2a2420",
      "--stash-bg-elevated": "#342c28",
      "--stash-bg-code": "#181410",
      "--stash-bg-hover": "#3e3430",
      "--stash-text-primary": "#f0e0d0",
      "--stash-text-secondary": "#a09080",
      "--stash-text-bright": "#fff0e0",
      "--stash-accent": "#fab387",
      "--stash-destructive": "#f38ba8",
      "--stash-border": "#38302a",
      "--stash-error": "#f38ba8",
    },
  },
  {
    id: "emerald",
    label: "Emerald",
    description: "Forest-dark base with fresh emerald-green accents",
    mode: "semi-dark",
    vars: {
      "--stash-bg-base": "#182020",
      "--stash-bg-surface": "#1e2a2a",
      "--stash-bg-elevated": "#263434",
      "--stash-bg-code": "#121a1a",
      "--stash-bg-hover": "#2e4040",
      "--stash-text-primary": "#d0f0d8",
      "--stash-text-secondary": "#70a080",
      "--stash-text-bright": "#e0fff0",
      "--stash-accent": "#a6e3a1",
      "--stash-destructive": "#f38ba8",
      "--stash-border": "#28383a",
      "--stash-error": "#f38ba8",
    },
  },
  {
    id: "nord-light",
    label: "Nord-Light",
    description: "Canonical Polar Night palette with bright Snow Storm text",
    mode: "semi-dark",
    vars: {
      "--stash-bg-base": "#2e3440",
      "--stash-bg-surface": "#3b4252",
      "--stash-bg-elevated": "#434c5e",
      "--stash-bg-code": "#242932",
      "--stash-bg-hover": "#4c566a",
      "--stash-text-primary": "#d8dee9",
      "--stash-text-secondary": "#6b7a99",
      "--stash-text-bright": "#eceff4",
      "--stash-accent": "#88c0d0",
      "--stash-destructive": "#bf616a",
      "--stash-border": "#56637a",
      "--stash-error": "#bf616a",
    },
  },

  // ── Dark ──────────────────────────────────────────────────────────────────
  {
    id: "midnight",
    label: "Midnight",
    description: "True near-black navy with electric blue accents",
    mode: "dark",
    vars: {
      "--stash-bg-base": "#0d0e1a",
      "--stash-bg-surface": "#111326",
      "--stash-bg-elevated": "#171930",
      "--stash-bg-code": "#08090e",
      "--stash-bg-hover": "#1b1d36",
      "--stash-text-primary": "#a8b0d0",
      "--stash-text-secondary": "#505878",
      "--stash-text-bright": "#c8d0f0",
      "--stash-accent": "#7aa2f7",
      "--stash-destructive": "#f7768e",
      "--stash-border": "#16183a",
      "--stash-error": "#f7768e",
    },
  },
  {
    id: "obsidian",
    label: "Obsidian",
    description: "Polished black surface with soft amethyst accents",
    mode: "dark",
    vars: {
      "--stash-bg-base": "#0f0f12",
      "--stash-bg-surface": "#161618",
      "--stash-bg-elevated": "#1e1e22",
      "--stash-bg-code": "#0a0a0c",
      "--stash-bg-hover": "#242428",
      "--stash-text-primary": "#c0b8d0",
      "--stash-text-secondary": "#605870",
      "--stash-text-bright": "#e0d8f0",
      "--stash-accent": "#bb9af7",
      "--stash-destructive": "#f7768e",
      "--stash-border": "#201e28",
      "--stash-error": "#f7768e",
    },
  },
  {
    id: "nord-dark",
    label: "Nord-Dark",
    description: "Deep sub-zero Polar Night with muted Frost accents",
    mode: "dark",
    vars: {
      "--stash-bg-base": "#191e28",
      "--stash-bg-surface": "#212736",
      "--stash-bg-elevated": "#2a3044",
      "--stash-bg-code": "#11151e",
      "--stash-bg-hover": "#303a50",
      "--stash-text-primary": "#b8c8d8",
      "--stash-text-secondary": "#4e5e72",
      "--stash-text-bright": "#d0e0f0",
      "--stash-accent": "#81a1c1",
      "--stash-destructive": "#bf616a",
      "--stash-border": "#2e3a4e",
      "--stash-error": "#bf616a",
    },
  },
];

const GROUPS: ThemeGroup[] = [
  { label: "Light", mode: "light", themes: THEMES.filter((t) => t.mode === "light") },
  { label: "Semi-Dark", mode: "semi-dark", themes: THEMES.filter((t) => t.mode === "semi-dark") },
  { label: "Dark", mode: "dark", themes: THEMES.filter((t) => t.mode === "dark") },
];

/** Custom event dispatched after a theme is applied. Components that
 * have already-rendered output baked from CSS vars (e.g. mermaid SVGs,
 * which inline their colors) listen for this and re-render. */
export const THEME_CHANGE_EVENT = "stash-theme-change";

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  Object.entries(theme.vars).forEach(([k, v]) => root.style.setProperty(k, v));
  localStorage.setItem("stash-theme", theme.id);
  window.dispatchEvent(
    new CustomEvent(THEME_CHANGE_EVENT, { detail: { themeId: theme.id, mode: theme.mode } }),
  );
}

/** Tiny mock-UI preview rendered entirely from a theme's raw color vars */
function ThemePreview({ theme }: { theme: Theme }) {
  const v = theme.vars;
  const isLight = theme.mode === "light";

  return (
    <div
      className="h-20 w-full overflow-hidden rounded-t-md flex flex-col"
      style={{ backgroundColor: v["--stash-bg-elevated"] }}
    >
      {/* Title bar */}
      <div
        className="flex items-center gap-1 px-2.5 py-1.5 shrink-0"
        style={{ backgroundColor: v["--stash-bg-elevated"] }}
      >
        <span
          className="w-2 h-2 rounded-full"
          style={{ backgroundColor: v["--stash-destructive"], opacity: 0.7 }}
        />
        <span
          className="w-2 h-2 rounded-full"
          style={{ backgroundColor: v["--stash-accent"], opacity: 0.5 }}
        />
        <span
          className="w-2 h-2 rounded-full"
          style={{ backgroundColor: v["--stash-text-secondary"], opacity: 0.4 }}
        />
      </div>

      {/* Body: sidebar + content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Sidebar */}
        <div
          className="w-12 shrink-0 flex flex-col gap-1 px-1.5 py-1.5"
          style={{ backgroundColor: v["--stash-bg-surface"] }}
        >
          <div
            className="h-1.5 rounded-sm"
            style={{ backgroundColor: v["--stash-accent"], opacity: 0.8, width: "70%" }}
          />
          <div
            className="h-1.5 rounded-sm"
            style={{ backgroundColor: v["--stash-text-secondary"], opacity: 0.4, width: "85%" }}
          />
          <div
            className="h-1.5 rounded-sm"
            style={{ backgroundColor: v["--stash-text-secondary"], opacity: 0.3, width: "60%" }}
          />
          <div
            className="h-1.5 rounded-sm"
            style={{ backgroundColor: v["--stash-text-secondary"], opacity: 0.3, width: "75%" }}
          />
        </div>

        {/* Content area */}
        <div
          className="flex-1 flex flex-col gap-1.5 px-2 py-1.5"
          style={{ backgroundColor: v["--stash-bg-base"] }}
        >
          <div
            className="h-2 rounded-sm"
            style={{ backgroundColor: v["--stash-text-bright"], opacity: isLight ? 0.55 : 0.7, width: "55%" }}
          />
          <div
            className="h-1.5 rounded-sm"
            style={{ backgroundColor: v["--stash-text-primary"], opacity: isLight ? 0.4 : 0.45, width: "90%" }}
          />
          <div
            className="h-1.5 rounded-sm"
            style={{ backgroundColor: v["--stash-text-primary"], opacity: isLight ? 0.3 : 0.35, width: "75%" }}
          />
          <div
            className="h-1.5 rounded-sm"
            style={{ backgroundColor: v["--stash-accent"], opacity: 0.5, width: "40%" }}
          />
        </div>
      </div>
    </div>
  );
}

export function AppearanceSettings() {
  const [activeTheme, setActiveTheme] = useState<string>(
    () => localStorage.getItem("stash-theme") ?? "teal",
  );

  function handleSelect(theme: Theme) {
    setActiveTheme(theme.id);
    applyTheme(theme);
  }

  return (
    <div>
      <h3
        className="text-base font-semibold mb-1"
        style={{ color: "var(--stash-text-bright)" }}
      >
        Appearance
      </h3>
      <p
        className="text-sm mb-6"
        style={{ color: "var(--stash-text-secondary)" }}
      >
        Choose a color theme. Changes apply instantly and are saved locally.
      </p>

      <div className="space-y-6">
        {GROUPS.map((group) => (
          <div key={group.mode}>
            {/* Group header */}
            <div className="flex items-center gap-3 mb-3">
              <span
                className="text-xs font-semibold uppercase tracking-widest"
                style={{ color: "var(--stash-text-secondary)" }}
              >
                {group.label}
              </span>
              <div
                className="flex-1 h-px"
                style={{ backgroundColor: "var(--stash-border)" }}
              />
            </div>

            {/* Theme grid */}
            <div className="grid grid-cols-3 gap-3">
              {group.themes.map((theme) => {
                const isActive = activeTheme === theme.id;
                return (
                  <button
                    key={theme.id}
                    onClick={() => handleSelect(theme)}
                    className="relative flex flex-col rounded-lg overflow-hidden text-left transition-all duration-150 outline-none"
                    style={{
                      border: isActive
                        ? `2px solid ${theme.vars["--stash-accent"]}`
                        : "2px solid var(--stash-border)",
                    }}
                    title={theme.description}
                  >
                    {/* Mini UI preview */}
                    <ThemePreview theme={theme} />

                    {/* Label strip */}
                    <div
                      className="flex items-center justify-between px-2.5 py-2 gap-1"
                      style={{
                        backgroundColor: "var(--stash-bg-surface)",
                        borderTop: "1px solid var(--stash-border)",
                      }}
                    >
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0"
                          style={{ backgroundColor: theme.vars["--stash-accent"] }}
                        />
                        <span
                          className="text-xs font-medium truncate"
                          style={{
                            color: isActive
                              ? "var(--stash-accent)"
                              : "var(--stash-text-bright)",
                          }}
                        >
                          {theme.label}
                        </span>
                      </div>

                      {isActive && (
                        <div
                          className="shrink-0 w-4 h-4 rounded-full flex items-center justify-center"
                          style={{ backgroundColor: theme.vars["--stash-accent"] }}
                        >
                          <Check
                            className="w-2.5 h-2.5"
                            style={{ color: theme.vars["--stash-bg-base"] }}
                          />
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Active theme info strip */}
      {(() => {
        const active = THEMES.find((t) => t.id === activeTheme);
        if (!active) return null;
        return (
          <div
            className="mt-6 flex items-center gap-3 px-4 py-3 rounded-md"
            style={{
              backgroundColor: "var(--stash-bg-base)",
              border: "1px solid var(--stash-border)",
            }}
          >
            <span
              className="w-3 h-3 rounded-full shrink-0"
              style={{ backgroundColor: active.vars["--stash-accent"] }}
            />
            <div className="flex-1 min-w-0">
              <span
                className="text-sm font-medium"
                style={{ color: "var(--stash-text-bright)" }}
              >
                {active.label}
              </span>
              <span
                className="text-xs ml-2"
                style={{ color: "var(--stash-text-secondary)" }}
              >
                {active.description}
              </span>
            </div>
            <span
              className="text-xs px-2 py-0.5 rounded capitalize"
              style={{
                backgroundColor: "var(--stash-bg-elevated)",
                color: "var(--stash-accent)",
                border: "1px solid var(--stash-border)",
              }}
            >
              {active.mode}
            </span>
          </div>
        );
      })()}
    </div>
  );
}