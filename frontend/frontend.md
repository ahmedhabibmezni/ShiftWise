# ShiftWise Frontend — Claude Code Prompt

> **How to use this file**
>
> 1. Open Claude Code in your `ShiftWise` repo on branch `develop`.
> 2. Run these commands first: `/model opusplan`, `/effort medium`, `/clear`.
> 3. Activate plan mode (`Shift+Tab` until you see "plan mode" in the status bar).
> 4. Copy everything below the `---` line and paste as your first message.
> 5. Approve the plan with `Approved.` when Claude Code presents it.

---

## Session policy — Claude Pro plan, conserve quota

I'm on Claude Pro running you as `/model opusplan` with `/effort medium` and plan mode ON.

- Use Opus thinking ONLY for the consolidated plan, architecture decisions, and the design system styleguide. Switch to Sonnet automatically for code generation.
- Do not load files into context with `@` unless strictly necessary. Use bare paths and tell me which files you'd want to open.
- Keep responses concise. Do not narrate at length what you're about to do — just do it and report briefly.
- I will run `/clear` between sessions. Each page after the styleguide must be self-contained enough that you don't need P1's context to build P3.

## Plan mode override

Treat the "Step 0" scaffold inventory + design system styleguide approval gate inside the prompt below as part of your single consolidated plan. Don't ask me twice.

Present ONE plan with:

1. Scaffold inventory (what exists in `frontend/`, what to keep, what to delete)
2. Design tokens preview (the CSS variables I can copy/paste mentally)
3. File tree you'll create
4. Dependency list with one-line justification each
5. Commit sequence

I approve once, then you execute through commit #2 (design system + `/styleguide` route only). After commit #2 I will `/clear` and start a new session for the next batch.

---

# ShiftWise Frontend — Build Plan

## Context — actual state of the project

You already have full context of this project. Branch: `develop`. Repo: `ahmedhabibmezni/ShiftWise`.

Backend status (real, not what the older report says):

- Auth + RBAC + multi-tenant: 100% (50+ endpoints)
- Hypervisors / VMs / Migrations / KubeVirt routers: 100%
- Discovery service: still in simulation mode (real pyvmomi/libvirt connectors not yet wired)
- **Analyzer module: COMPLETE** (compatibility scoring + classification COMPATIBLE / PARTIAL / INCOMPATIBLE)
- Disk conversion module: in progress
- Celery + Redis async migration engine: currently being wired (no real async task runs yet — `/start` just flips status to VALIDATING)
- Frontend scaffold: ~20% — Vite + React + TS + Tailwind + Shadcn + Zustand + Axios + JWT refresh interceptor + service classes already in place

Backend runs at `http://localhost:8000`, OpenAPI at `/openapi.json`, Swagger at `/docs`. CORS already configured.

Before writing ANY code, run `git status` and `ls -la frontend/ frontend/src/` and tell me what scaffold files already exist. I will tell you what to keep vs throw away. Do NOT assume.

## Non-negotiable architecture rules

1. **Typed API client from OpenAPI**, never hand-written types.
   - `openapi-typescript` against `http://localhost:8000/openapi.json` → `src/api/schema.gen.ts`
   - `openapi-fetch` as the typed client.
   - npm script `gen:api` so I rerun after backend changes.
   - Keep the existing Axios JWT-refresh interceptor — wire openapi-fetch through it. Do not duplicate auth logic.

2. **Server state via TanStack Query.** Zustand stays for auth and UI state only. Replace any service-class fetch calls with query hooks.

3. **Migration progress = polling, abstracted.**
   - Hook: `useMigrationProgress(migrationId)` in `src/hooks/useMigrationProgress.ts`
   - Implementation: `useQuery` with `refetchInterval: 2000` while status is in {PENDING, VALIDATING, PREPARING, EXPORTING, CONVERTING, IMPORTING, FINALIZING}, stops polling on terminal status.
   - Add a comment: "If WebSocket support is added backend-side later, swap implementation here only — public API unchanged."

4. **Mocks via MSW, partial scope only.**
   - Mock these endpoints (backend behavior unstable or not real): `/hypervisors/{id}/sync`, `/hypervisors/test-connection`, and migration `/start` async progression.
   - Analyzer endpoints (`/vms/{id}/analyze`, `/vms/{id}/analyze/batch`, `/vms/{id}/analyze/stats`) are COMPLETE backend-side — DO NOT mock unless I tell you the real response is unstable.
   - All other endpoints hit real backend.
   - Toggle: `VITE_USE_MOCKS=true` enables MSW for the partial set; default is `false`.

5. **Forbidden dependencies.** Do not install: framer-motion, gsap, three.js, lottie, react-spring, redux, jotai, recoil, mui, antd, chakra, mantine, styled-components, emotion, react-hook-form. If you think you need one, stop and ask.

## Design system — strict, no deviations

You will be tempted to default to: dark dashboard with purple/cyan accents, glassmorphism cards, gradient hero, glowing CTAs, rounded-2xl, shadow-2xl, framer-motion entrance animations, emoji icons, "AI sparkle" effects on Analyzer button. **All of that is forbidden.** This brief is restraint.

Reference aesthetics (mentally study these before coding): Bloomberg Terminal, Linear early version, Vercel Observability tab, Rauno Freiberg's site, industrial SCADA dashboards, NASA mission control consoles, Datadog terminal log views.

### Tokens — `src/styles/tokens.css` + Tailwind theme extension

Light mode (default; toggle in header; respects `prefers-color-scheme` on first visit; persist to `localStorage` afterwards):

```css
--bg: #f5f1e8; /* bone */
--bg-elev: #ece6d5; /* panel */
--ink: #14110d;
--ink-muted: #6b6557;
--line: #1a1a1a; /* 1px borders, used heavily */
--line-soft: #c9c2b0;
--signal: #d6541c; /* single accent — actions, primary CTAs */
--info: #2b4a6f; /* steel blue — neutral info, links */
--ok: #1f7a3a;
--warn: #b8860b;
--err: #b53024;
```

Dark mode:

```css
--bg: #0e0e0e;
--bg-elev: #161616;
--ink: #e8e4da;
--ink-muted: #8a8478;
--line: #2a2a2a;
--line-soft: #1f1f1f;
--signal: #e8642a;
--info: #4a7bb0;
--ok: #2d9f50;
--warn: #d4a017;
--err: #cc4030;
```

### Typography

- Body: `Inter Tight`, weights 400/500/600 only.
- Mono: `JetBrains Mono`, weights 400/500.
- Sizes (px, no other values): 11, 12, 13, 14, 16, 20, 28. Nothing larger than 28 anywhere.
- Line-height: 1.4 body, 1.1 mono blocks, 1.0 numeric tables.
- Numbers in tables and stats: ALWAYS mono, ALWAYS `font-variant-numeric: tabular-nums`, ALWAYS right-aligned.

### Layout

- 12-column grid, 16px gutter, max-width 1440px.
- Borders define the layout: `1px solid var(--line)`. Use them generously.
- Border radius: 0px default, 2px allowed on buttons/inputs, NEVER more.
- Shadows: forbidden. Single exception: slide-in panel uses a 1px right-shifted border-shadow, no blur.
- Spacing scale (px): 4, 8, 12, 16, 24, 32, 48. Nothing else.

### Components

- **Buttons.** 32px height, 1px border, 2px radius. Action labels in mono uppercase, letter-spacing 0.05em (e.g. `LANCER MIGRATION`). Primary = signal bg + white text. Secondary = transparent + line border. Danger = err bg + white. No gradient, no shadow, no hover scale.
- **Inputs.** 32px height, 0px radius, 1px line border. Focus state: 1px signal-color outline offset 1px (no glow, no shadow).
- **Tables.** Dense rows 32px. NO zebra striping. Hover row = `bg-elev`. Sticky header with double bottom border (1px line + 1px line-soft below). Column headers = mono uppercase 11px.
- **Status badges.** NOT pills. 2px-radius rectangles, mono uppercase 11px, with a leading 6px square color dot.
- **Panels.** Rectangle, 1px border, label in top-left in mono uppercase 11px (SCADA-style: `MIGRATION QUEUE — 03 ACTIVE`).
- **Slide-in panel.** 480px wide, slides from right, 120ms ease-out, backdrop = `rgba(0,0,0,0.4)` (no blur). Replaces shadcn Dialog everywhere.
- **Progress bar.** 4px tall, signal color fill on bg-elev track, no rounded ends. Active migration shows percentage to right in mono tabular-nums.
- **Live indicator.** 8x8px square, signal color, opacity animation 1 → 0.3 → 1 over 1.6s. Used sparingly, only on actively-running operations.

### Iconography

`lucide-react` only. Stroke-width 1.5. Sizes 16px or 20px only. NEVER filled icons. NEVER emoji in UI.

### Animation budget

- Transitions: 120ms ease-out max. Properties allowed: opacity, border-color, background-color, transform (translate only, no scale).
- Top-of-page progress bar (NProgress style, 1px tall, signal color) for route changes and global loading.
- No spinners. No skeleton shimmer with gradient — use static `bg-elev` blocks instead.
- No entrance animations on lists, cards, or page loads.

## Pages — build in this order, one commit per page

**P1. `/login`** — Split layout. Left half = bone bg, ASCII-art "SHIFTWISE" logo (figlet ANSI Shadow font, paste as `<pre>`), version string, git commit hash from `VITE_BUILD_HASH`, build date. Right half = login form, 320px wide, centered. No marketing copy, no illustration.

**P2. `/` Dashboard** — Top row: 4 KPI panels (Hyperviseurs connectés / VMs découvertes / Migrations en cours / Taux de succès 30j). Each = 1px-bordered rectangle, label top-left mono uppercase, big number 28px mono tabular-nums, delta vs previous period below in 11px ink-muted. Middle row, 2 columns: left = "MIGRATION QUEUE" table (top 8 active or recent migrations); right = "ACTIVITY LOG" terminal-style scrolling feed (bg = ink, text = bg, mono 12px, format `[HH:MM:SS] user@action target`). Bottom: "COMPATIBILITY DISTRIBUTION" — horizontal stacked bar (not donut), 3 segments OK/PARTIAL/INCOMPATIBLE with mono legend below showing counts and percentages.

**P3. `/hypervisors`** — Top bar: search input (left) + type filter dropdown + status filter dropdown + `[+ AJOUTER]` button (right). Table columns: NAME, TYPE, HOST, STATUS, LAST_SYNC, VMS, ACTIONS. STATUS uses status badge component. LAST_SYNC = relative time (date-fns), VMS = mono number right-aligned. Row click → slide-in panel with full details + test-connection + sync + edit buttons.

**P4. `/hypervisors/new`** — Centered 480px column. Form sections separated by 1px line-soft horizontal lines. Sections: "IDENTIFICATION" (name, type select, description), "CONNEXION" (host, port, credentials), "CONFIGURATION" (datacenter, default folder if vSphere). Submit area right-aligned: `[ANNULER] [TESTER LA CONNEXION] [ENREGISTRER]`. zod validation, errors inline below field in err color, 11px mono.

**P5. `/vms`** — Same table pattern. Columns: NAME, OS, vCPU, RAM, DISK_TOTAL, COMPATIBILITY, HYPERVISOR, ACTIONS. COMPATIBILITY = status badge with score in tooltip (Analyzer is done, real scores available). RAM and DISK in mono with units (`8.0 GB`, `120 GB`). Action buttons in row: "ANALYSER" if `compatibility_status` is null, "DÉTAILS" otherwise. Row click → slide-in panel showing full analysis report from `/vms/{id}/analyze` response: score, issues array, recommended_strategy.

**P6. `/migrations`** — Table columns: ID (short like `mig-7f3a`), VM, STRATEGY (mono uppercase), STATUS (badge), PROGRESS (4px bar + mono percentage right-aligned), STARTED_AT, DURATION, ACTIONS. Active rows show live indicator dot at left of ID. Row click → navigate to `/migrations/:id`.

**P7. `/migrations/:id`** — Full-page detail. Three-column: left rail (240px) = vertical phase stepper, each step = mono uppercase label + status icon + duration. Phases align to migration model statuses (PENDING → VALIDATING → PREPARING → EXPORTING → CONVERTING → IMPORTING → FINALIZING → COMPLETED, or → FAILED at any step). Center = live log stream (terminal block, ink bg, mono 12px, auto-scroll, with pause toggle). Right rail (320px) = metadata (VM info, source hypervisor, target namespace, strategy, started/ended, duration) + action buttons stacked: `[ANNULER]` (only if not terminal), `[ROLLBACK]` (only if FAILED with rollback eligible), `[TÉLÉCHARGER LE RAPPORT]`.

**P8. `/settings`** — Three tabs (1px-bordered tab strip, no rounded corners): "PROFIL" (current user info, change password), "UTILISATEURS" (table, admin only, CRUD), "RÔLES" (table, system roles read-only marked, custom roles editable). If RBAC permission missing, show panel with mono message `INSUFFICIENT PERMISSIONS — REQUIRES role.users.manage`.

**P9. `/infrastructure`** (feature 002, Administration) — Per-tenant cluster connection config. Scope selector (platform-default + tenant overrides). Mode editor (`kubeconfig` / `incluster` / `custom`): `kubeconfig` → file upload, `custom` → `api_url` + bearer token + `verify_ssl`, `incluster` → no input (valid only for platform-default). `[TESTER LA CONNEXION]` runs a live probe and renders a cluster-details panel (server version, platform, node/namespace counts, API URL) or the failure reason. Secrets are write-only — the read model never returns a kubeconfig/token, only `has_credentials`. RBAC: superadmin any scope, tenant admin own scope only; missing `infrastructure` permission hides the page.

## App shell

- **Header** (48px, 1px bottom border): left = SHIFTWISE wordmark in mono 14px + version, right = theme toggle (sun/moon lucide, 16px) + user menu (initials in 24px square, click → slide-in with profile/logout).
- **Sidebar** (56px, icon-only, 1px right border): Dashboard / Hyperviseurs / VMs / Migrations / Settings / Infrastructure (Administration, RBAC-gated). Active = signal-color 2px left bar + signal icon. Tooltip on hover (mono 11px, bg-elev, 1px border, 120ms delay).
- **Main**: 24px padding, 1440px max-width centered.
- **Top progress bar** when route is loading or any global query is fetching.

## Stack additions (justify or reject)

ADD:

- `openapi-typescript` + `openapi-fetch`
- `@tanstack/react-query` + devtools (dev only)
- `react-router-dom@6`
- `msw` (dev only)
- `zod`
- `date-fns`
- `clsx` + `tailwind-merge` (already shadcn-standard)

REJECT and challenge me if I ask for: anything from the forbidden list above.

## Build sequence (commit after each)

1. `chore(frontend): inventory existing scaffold` — list what's there, propose deletions, wait for my approval.
2. `feat(frontend): design system v1` — fonts, tokens.css, tailwind theme, build `/styleguide` route showing every component (button states, input states, table, badge, panel, slide-in, progress bar, live indicator). I review BEFORE any pages.
3. `feat(frontend): typed api client + react-query setup`
4. `feat(frontend): partial msw mocks`
5. `feat(frontend): app shell + theme toggle`
6. P1 → P8, one commit per page using conventional commits.
7. `docs(frontend): readme`

## Definition of done

- `npm run dev` on `http://localhost:5173`, full UI navigable against running backend.
- `VITE_USE_MOCKS=true npm run dev` works for offline development.
- `npm run gen:api` regenerates types.
- Lighthouse perf + a11y > 90 on every page.
- Zero console warnings in dev.
- All UI text in French, all code/comments/commits in English.
- Conventional commits, single-line messages (no multi-line bodies — house style).

## Final reminder

Restraint. Density. Borders not shadows. Mono for numbers. Single accent (signal). No purple. No glassmorphism. No emoji. No gradient. No glow. If you find yourself adding "polish", remove it.

**Step 0: Run `git status` + `ls -la frontend/ frontend/src/` and present ONE consolidated plan as described above. Do not start coding until I approve.**

---

# Session-by-session plan after the first approval

After the first plan is approved and commits 1–2 land, run this in order. **One `/clear` between every line.** Re-set `/model opusplan` and `/effort medium` after each clear if they don't persist.

| #   | Command to type into Claude Code                                                  | Scope          |
| --- | --------------------------------------------------------------------------------- | -------------- |
| 1   | `Build commits 3, 4, 5: API client + MSW + app shell. Follow the original brief.` | Infrastructure |
| 2   | `Build P1 (login) and P2 (dashboard) per the brief. Two commits.`                 | Pages 1–2      |
| 3   | `Build P3 (hypervisors list) and P4 (hypervisor new). Two commits.`               | Pages 3–4      |
| 4   | `Build P5 (vms) and P6 (migrations list). Two commits.`                           | Pages 5–6      |
| 5   | First `/effort high`, then: `Build P7 (migration detail). Single commit.`         | Complex page   |
| 6   | First `/effort medium`, then: `Build P8 (settings) and the readme. Two commits.`  | Final          |

After commit 2 (design system) — open `http://localhost:5173/styleguide` in a browser and **actually look**. If anything is off, fix it before going further. The whole frontend will inherit from this one screen.
