# Gantt Chart Format

Stash renders `.gantt` files (and ` ```gantt ` fenced blocks in markdown) as interactive Gantt charts via `stash-gantt.js`. The format is YAML and **specific to Stash** — it is not Mermaid gantt syntax and is not compatible with other Gantt tools.

This reference is the authoritative schema. Use it when authoring or editing gantt content; do not extrapolate from other Gantt libraries.

## Schema at a glance

```yaml
title: <string, optional>     # rendered as the chart title; defaults to "Gantt Chart"
sections:                     # required, array of sections
  - name: <string>            # section label (rendered as a grouping header)
    tasks:                    # array of tasks within this section
      - id: <string>          # stable identifier; required if other tasks depend on this one
        title: <string>       # rendered on the bar and in tooltips
        start: <YYYY-MM-DD>   # required
        duration: <Nd>        # e.g. "7d" or just a number (days); used if `end` is absent
        end: <YYYY-MM-DD>     # optional; takes priority over `duration` if both are set
        depends: <task id>    # optional; draws a dependency arrow from the referenced task
```

### Field rules

- **`sections` is required.** Without it the renderer shows "Invalid gantt data: missing sections".
- **`start` is required** on every task. Dates must be parseable by JavaScript's `new Date()` — use `YYYY-MM-DD` (canonical).
- **End-of-task is computed in this priority order:**
  1. `end:` if present (parsed as a date)
  2. `duration:` if present (`"7d"`, `7`, or any integer-string of days)
  3. Default: 7 days after `start`
- **`id` is optional** but required for `depends` to work. Use short, kebab-case ids (`design-review`, `api-v2-ship`).
- **`depends` takes a single task id** — it draws a curved arrow from that task's end to this task's start. The dependency does not constrain dates; it's purely visual.
- **Section colors** are auto-assigned in order (teal, blue, mauve, peach, green, pink, sky, lavender, yellow, flamingo) and cycle if there are more than 10 sections.

## Minimal example

```yaml
title: Q3 Roadmap
sections:
  - name: Foundations
    tasks:
      - id: schema
        title: Finalize schema
        start: 2026-07-01
        duration: 10d
      - id: migrate
        title: Run migration
        start: 2026-07-15
        duration: 3d
        depends: schema
```

## Full example with multiple sections and dependencies

```yaml
title: Stash 1.0 release plan
sections:
  - name: Design
    tasks:
      - id: api-design
        title: API surface review
        start: 2026-06-01
        duration: 7d
      - id: ux-pass
        title: UI/UX consistency pass
        start: 2026-06-08
        duration: 5d
        depends: api-design

  - name: Implementation
    tasks:
      - id: backend
        title: Backend changes
        start: 2026-06-15
        duration: 14d
        depends: api-design
      - id: frontend
        title: Frontend changes
        start: 2026-06-15
        end: 2026-07-05
        depends: ux-pass

  - name: Release
    tasks:
      - id: rc
        title: Release candidate
        start: 2026-07-08
        duration: 3d
        depends: backend
      - id: ship
        title: Ship 1.0
        start: 2026-07-15
        duration: 1d
        depends: rc
```

## Embedding in markdown

Inside a markdown document, wrap the YAML in a fenced block tagged `gantt`:

````markdown
Project timeline:

```gantt
title: Sprint 24
sections:
  - name: Tickets
    tasks:
      - id: t1
        title: Investigate flaky tests
        start: 2026-05-20
        duration: 3d
```
````

The fenced-block path is rendered client-side by posting the YAML to `/ui/parse-gantt`. Standalone `.gantt` files are parsed server-side. Both routes produce the same chart.

## Authoring guidance

- **Always set explicit `id`s** when you have more than one task per section — even if nothing depends on them yet. Re-introducing ids later requires updating every `depends` reference.
- **Prefer `duration` over `end`** for tasks where the length is the meaningful property (e.g. "two-week sprint"). Use `end` for tasks anchored to a hard deadline.
- **Group by team or workstream, not by time.** Sections are visual grouping; the timeline axis already conveys ordering.
- **Keep titles short** (< 40 chars). Long titles overflow the label column and clip on the bar.
- **The interactive viewer lets users drag bars to reschedule** and save back to disk. If a file is meant to be a fixed plan, note that in the surrounding doc — there's no read-only flag in the YAML itself (the UI sets `readOnly` based on store config, not file metadata).

## What this format is *not*

- Not Mermaid gantt syntax (`gantt\n  dateFormat YYYY-MM-DD\n  section Foo`). That will not render.
- Not MS Project XML, not `.gantt` from GanttProject, not Asana exports.
- Not a constraint solver — `depends` is visual only; dragging a predecessor does not move dependents.

If you find yourself writing `gantt\n  dateFormat ...`, stop. That's Mermaid. Use the YAML schema above.
