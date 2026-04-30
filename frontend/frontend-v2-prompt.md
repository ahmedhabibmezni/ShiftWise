# ShiftWise Frontend — Direction v2 "Brutalist Console"

> **Comment utiliser ce fichier**
>
> 1. Le précédent styleguide est rejeté. On repart from scratch avec une nouvelle direction artistique.
> 2. Tu vas joindre une **image de référence** à ton message Claude Code (le screenshot dark mode que tu as utilisé).
> 3. Lance `claude` dans `C:\Users\PC\OneDrive\Bureau\ShiftWise`, branche `develop`.
> 4. Commandes : `/model opusplan`, `/effort medium`, `/clear`, puis active plan mode (Shift+Tab).
> 5. Joins l'image en pièce jointe à ton premier message.
> 6. Copie tout ce qui est sous la ligne `---` ci-dessous.
> 7. Approuve avec `Approved.` quand le plan te semble bon.
> 8. **Ne lance RIEN d'autre tant que le styleguide v2 ne te plaît pas visuellement.**

---

## Session policy — Claude Pro plan, conserve quota

I'm on Claude Pro running you as `/model opusplan` with `/effort medium` and plan mode ON.

- Use Opus thinking ONLY for the consolidated plan and the styleguide v2 implementation. Switch to Sonnet automatically for routine code.
- Do not load files into context with `@` unless strictly necessary.
- Keep responses concise. Do not narrate at length — just do it and report briefly.
- I will run `/clear` between sessions. Each future session must be self-contained.

## Plan mode override

Treat the "Step 0" actions inside the prompt below as part of your single consolidated plan. Don't ask me twice.

Present ONE plan with:

1. List of files to **delete** from the previous attempt
2. New design tokens (CSS variables for both modes)
3. New `/styleguide` route file tree
4. Dependency check (anything new vs the previous attempt?)
5. Single commit message

I approve once, then you execute commit #1 (styleguide v2 only). I will then verify visually in the browser before approving the rest of the build.

---

# ShiftWise Frontend — Brutalist Console v2

## Critical context — read this first

The previous styleguide attempt was REJECTED. Reasons (so you don't repeat the mistakes):

- It was flat: every section had the same 1px border + same top-left label, no visual hierarchy
- It was empty: too many "boxed sections with a label" and no real content density
- It was a wireframe, not a design — looked like a Figma low-fidelity scaffold
- KPIs were too small (28px) and lived inside boxes — they should DOMINATE the page
- Single accent color (orange) was used decoratively, not semantically
- Zero personality, zero confidence, zero opinion

**Action 1**: DELETE these files completely (do NOT try to refactor them):

- `frontend/src/routes/styleguide.tsx` (and any related route file)
- `frontend/src/styles/tokens.css`
- Any tailwind theme extensions related to the previous design system

After deletion, rebuild from scratch following this brief.

## Visual reference

I have attached a screenshot to this message. **Study it carefully.** This is the visual direction. It is INSPIRATION, not a pixel-perfect copy target. What matters about that screenshot:

1. **Radical hierarchy by size.** The "23" is enormous. The "07 / 1.289 / 93.6%" are large but smaller. The CPU/memory/storage stats are smaller again. You can read the entire dashboard in 2 seconds.
2. **Full-bleed colored blocks as semantic zones.** Orange = "active critical operations happening right now". Steel blue = "stable informational area". Graphite/black = neutral data.
3. **Volunteered asymmetry.** Orange block ~50% wide, blue block ~50% on a different row, KPIs are different sizes by importance.
4. **High but breathable density.** The migration queue table on the right has 7 columns and stays readable. The mini-table inside the orange block is tight but airy.
5. **Telling details.** Avatar in sidebar, "12" badge on alerts, footer with uptime/region/version, persistent orange "+ nouvelle migration" CTA bottom-right.

Do NOT copy this image pixel-perfect. Use it to calibrate proportions, hierarchy, and confidence.

## Non-negotiable design DNA — Brutalist Console

You will be tempted to "modernize" or "soften" what you see in the reference. **Resist.** Specifically:

- ❌ NO subtle shadows. No `shadow-sm`, `shadow-md`, `shadow-lg`. Borders only.
- ❌ NO rounded corners larger than 4px. Buttons and inputs max 4px. Cards/blocks 0px.
- ❌ NO gradient overlays. Solid color blocks only.
- ❌ NO hover states with `transform: scale()`. Translate by 2-4px max, 150ms.
- ❌ NO glassmorphism, backdrop-blur, semi-transparent overlays (except modal backdrop)
- ❌ NO emoji as functional icons. Lucide only.
- ❌ NO "AI sparkle" effects, glow, neon
- ❌ NO skeleton shimmer loading. Use static `bg-elev` blocks
- ❌ NO entrance animations on lists, cards, page loads
- ❌ NO purple, no cyan, no pastel anywhere

**If you find yourself adding "polish" to make it feel more like Linear/Stripe/Vercel, STOP and remove it.** The brief is brutalist confidence, not premium SaaS smoothness.

## Tokens — `src/styles/tokens.css` + Tailwind theme

### Dark mode (default — matches the reference image)

```css
--bg: #0f1115; /* deep graphite */
--bg-elev: #181b22; /* panel */
--bg-elev-2: #20242c; /* nested elev */
--ink: #f4f2ec; /* primary text — bone white on dark */
--ink-muted: #8c8b85;
--line: #2a2d34;
--line-strong: #3a3d45;

--signal: #e8551f; /* orange — critical/active operations only */
--signal-ink: #ffffff; /* text on signal blocks */
--info: #2b4a6f; /* steel blue — stable info zones */
--info-ink: #f4f2ec;
--ok: #3faf5f;
--warn: #d4a017;
--err: #d04030;
```

### Light mode (toggle, same DNA, NOT a marketing-friendly version)

```css
--bg: #f2efe6; /* bone */
--bg-elev: #e6e1d2;
--bg-elev-2: #dcd6c2;
--ink: #14110d;
--ink-muted: #6b6557;
--line: #14110d; /* dark borders on light bg */
--line-strong: #000000;

--signal: #d6541c; /* slightly more saturated for light contrast */
--signal-ink: #ffffff;
--info: #244062;
--info-ink: #f2efe6;
--ok: #1f7a3a;
--warn: #b8860b;
--err: #b53024;
```

Default mode: respects `prefers-color-scheme` on first visit, then `localStorage` overrides.

## Typography — strict, two families only

- **Body / labels / headlines**: `Inter`, weights 400/500/600/700/800. No other sans-serif.
- **Numbers / IDs / timestamps / code**: `JetBrains Mono`, weights 400/500. Always with `font-variant-numeric: tabular-nums`.
- The mono is reserved for: numeric values in any KPI/table/badge, identifiers like `vm-312`, `mig-7f3a`, timestamps `14:22:01`, version strings, durations like `2m 14s`, file sizes `2.1 TB`, percentages.
- Everything else (button labels, navigation, headlines, paragraph text) is `Inter`.

### Type scale (tight — no in-between sizes allowed)

| Token          | Size                          | Family         | Usage                                         |
| -------------- | ----------------------------- | -------------- | --------------------------------------------- |
| `text-display` | 80px / weight 800 / line 0.95 | Inter          | KPI hero number (e.g. "23")                   |
| `text-major`   | 56px / weight 700 / line 1.0  | Inter          | Section dominant numbers ("07", "1.289")      |
| `text-h1`      | 32px / weight 700 / line 1.1  | Inter          | Page titles ("overview")                      |
| `text-h2`      | 24px / weight 600 / line 1.2  | Inter          | Big block headlines ("tout est opérationnel") |
| `text-h3`      | 16px / weight 600 / line 1.3  | Inter          | Section labels ("migrations en cours")        |
| `text-body`    | 14px / weight 400 / line 1.5  | Inter          | Body text                                     |
| `text-meta`    | 12px / weight 400 / line 1.4  | Inter          | Captions, deltas, hints                       |
| `text-mono-lg` | 18px / weight 500             | JetBrains Mono | Mid-size numeric stats                        |
| `text-mono`    | 13px / weight 400             | JetBrains Mono | Table values, IDs, timestamps                 |
| `text-mono-sm` | 11px / weight 500             | JetBrains Mono | Status badge labels, tiny mono labels         |

**Casing rule**: page titles and section labels are **lowercase** (e.g. `overview`, `migrations en cours`, `infrastructure`) — that's a deliberate brutalist signature, not a typo. Status badges and button labels stay UPPERCASE for action emphasis.

## Layout system

- 12-column grid, 24px gutter, max-width 1440px
- Spacing scale (px, no other values): 4, 8, 12, 16, 24, 32, 48, 64, 96
- Sidebar: 80px wide, full height, `bg-elev`, 1px right border `line-strong`
- Header: 64px tall, full width, 1px bottom border
- Footer/folio: 48px tall, full width, mono meta info (uptime, region, version)
- Main content: 32px padding, fills remaining space

## Components — concrete specifications

### Sidebar (left, 80px)

- Logo block at top: 64x64px, contains `SW` mono uppercase, 24px, weight 700
- Nav items: icon (lucide stroke 1.5, 20px) above mono uppercase 11px label
- Active item: `signal` color text + icon, 2px left bar in `signal`, no background change
- Hover: `bg-elev-2` background, 150ms transition
- Bottom: avatar 32x32px (square, 2px radius) + username/role mono 11px stacked, click → slide-in profile

### Header (top, 64px)

- Left: page title in lowercase Inter `text-h1` (e.g. `overview`), 32px from left edge
- Right cluster (32px from right):
  - Live indicator: 12x12px square `signal`, pulsing opacity 1→0.4→1 over 1.6s, label `live` mono 12px
  - Timestamp: mono 12px `14:22:01 UTC`
  - Range selector: dropdown styled like a button, mono 12px (`last 24h`)
- 1px bottom border `line`

### KPI block — primary (the "23" treatment)

- Full background color (signal or info), no border
- Padding 32px
- Top label: `text-h3` (Inter 16px) in `signal-ink` or `info-ink`, lowercase
- Hero number: `text-display` (80px Inter weight 800), color = ink-on-block
- Optional: footer rule 1px (line-strong on light, line on dark) + mini table below

### KPI block — secondary (the "07 / 1.289 / 93.6%" treatment)

- `bg-elev` background, 1px `line` border
- Padding 24px
- Top label: `text-h3` lowercase
- Number: `text-major` (56px) in `ink`, mono not needed for clean display numbers
- Bottom: delta indicator with arrow ↑/↓ + mono 12px value + ink-muted `vs 24h`
- Delta color: `ok` if positive direction, `err` if negative, `ink-muted` if neutral

### Mini-table inside colored blocks (the migration list inside orange block)

- No row borders, no zebra
- 4 columns: source/target with arrow `→`, vm id mono, percentage mono, progress bar
- Progress bar: 4px tall, signal-ink color on signal-ink/30 track, full-width within column
- Right edge: size mono + duration mono + chevron `→` icon
- Row height 40px, hover = subtle bg-darken (5% darker than block bg)

### Standard table (migration queue, hypervisors list)

- Header row: 32px tall, mono uppercase 11px in `ink-muted`, no border bottom (use a 1px `line-strong` separator below the entire header row instead)
- Body rows: 40px tall, no zebra, hover = `bg-elev-2`
- Cell alignment: numbers right-aligned mono, text left-aligned Inter
- Status column: badge component
- Last column actions: icon button or chevron, hover only

### Status badge

- Rectangle with 2px radius
- Padding 4px 8px
- Mono uppercase 11px weight 500
- Leading 6px square color dot (4px gap to label)
- Background: 12% opacity of status color on dark, 8% on light
- Text color: full status color
- States: `compatible` (ok), `partial` (warn), `incompatible` (err), `info`, `unknown` (ink-muted)

### Buttons

- Height 40px (NOT 32px — bigger and more confident than v1)
- Padding horizontal 16px
- Border radius 2px
- Label: Inter weight 600, 14px, NOT uppercase by default. Uppercase only for primary CTAs that demand emphasis.
- **Primary**: `signal` background, `signal-ink` text, no border. Hover: 5% darker background.
- **Secondary**: transparent background, 1px `line-strong` border, `ink` text. Hover: `bg-elev` background.
- **Danger**: `err` background, white text, no border. Hover: 5% darker.
- **Ghost** (used for table actions): no background, no border, `ink-muted` text + icon. Hover: `bg-elev` background, `ink` text.
- Icon-only button: 40x40px square, same states.

### Inputs

- Height 40px, padding 12px, border radius 2px
- 1px `line` border, hover `line-strong`, focus `signal` 1px outline + 0px offset
- `bg-elev` background
- Inter 14px text
- Label above (mono uppercase 11px ink-muted, 8px gap)
- Error: 1px `err` border + `err` 12px message below

### Alert/Activity row (the alerts list)

- 56px tall, 1px bottom `line` separator (last has none)
- Left: 8x8px circle (NOT square here — circles distinguish alerts from status badges) in priority color (`err`/`signal`/`warn`/`info`)
- Then mono 12px timestamp `14:21`, 16px gap
- Then Inter 14px message
- Right: severity badge (`critical`/`high`/`medium`/`low` — using same status badge component but with severity colors) + chevron `→`
- Hover: `bg-elev-2`, click → slide-in detail panel

### Slide-in panel

- Width 480px on desktop, 100% on mobile
- Slides from right, 200ms ease-out (a bit longer than v1 — these need confidence)
- Backdrop `rgba(0,0,0,0.5)`, NO blur
- Header: 64px tall with title `text-h2` lowercase + close icon button
- Content: 32px padding
- Footer with action buttons right-aligned

### Live indicator

- 12x12px square (NOT 8 — bigger to read)
- `signal` color
- Pulsing opacity animation: `1 → 0.4 → 1` over 1.6s, ease-in-out, infinite
- Optional label `live` in mono 12px next to it

### Progress bar

- Height 4px (kept from v1, this works)
- No rounded ends
- Track: 20% opacity of fill color
- Fill: solid color (signal in active migrations, ok when complete)
- Optional right-side mono percentage

## Pages to build (LATER — after styleguide v2 is approved)

You'll build these in subsequent sessions, NOT in this commit. List for context only:

- P1 `/login` — split layout, asymmetric, brand block on left with massive `SHIFTWISE` wordmark, login form on right
- P2 `/` Dashboard — matches the reference image structure: sidebar + header + asymmetric KPI grid + alerts/queue split + footer folio
- P3 `/hypervisors` — table-heavy list page
- P4 `/hypervisors/new` — form, single column 480px
- P5 `/vms` — table list with compatibility badge column
- P6 `/migrations` — table list with progress bars and live indicators
- P7 `/migrations/:id` — three-column detail (stepper rail / log stream / metadata rail)
- P8 `/settings` — tabbed page

## Step 0 — what to do RIGHT NOW

1. Run `git status` and `ls frontend/src/routes/ frontend/src/styles/ 2>/dev/null` and report
2. Confirm the deletion list (the previous styleguide files)
3. Present the consolidated plan with:
   - Files to delete
   - New file tree for styleguide v2
   - Tokens preview (just confirm the values above are what you'll use)
   - New `/styleguide` route content outline (which sections, in what order)
   - Single commit message
4. STOP and wait for `Approved.`

Once approved, execute one commit: `feat(frontend): design system v2 — brutalist console`

Show me a fully populated `/styleguide` page that demonstrates EVERY component above, with realistic content (use the reference image content as inspiration: real-looking hypervisor names like `vsphere-prod-01`, real VM ids like `vm-312`, real timestamps, real sizes). Empty placeholder demos are forbidden — every section must look like it could be a real piece of the dashboard.

After commit, I will:

- Run `npm run dev`
- Open `/styleguide` in BOTH light and dark modes
- Either approve (we proceed to build the API client + pages) or reject with specific changes

If I reject, you fix in a single follow-up commit, no full rewrite.

---

# Anti-drift checklist (Claude, re-read this before every styling decision)

1. Am I adding a shadow? **STOP.** Use a border instead.
2. Am I rounding corners more than 4px? **STOP.** Reduce to 0-2px.
3. Am I making this section feel "softer" or "more polished"? **STOP.** That's the wrong direction.
4. Am I about to add `transition-all` or animate `transform: scale`? **STOP.** Only opacity, color, and 4px translate.
5. Does this look like Linear/Stripe/Vercel? **STOP.** Make it more confident, more asymmetric, more typographically bold.
6. Am I using `signal` (orange) decoratively? **STOP.** Orange is reserved for active critical operations only.
7. Am I making KPI numbers small to "fit"? **STOP.** Bigger. The hero number is supposed to dominate.
8. Am I using emoji or decorative icons? **STOP.** Lucide stroke 1.5, only.

If any answer is yes, undo and reconsider.

---

# Session plan after styleguide v2 is approved

| #   | Command                                                                                                             | Scope          |
| --- | ------------------------------------------------------------------------------------------------------------------- | -------------- |
| 1   | (this prompt) — styleguide v2 only                                                                                  | Foundation     |
| 2   | `Build the API client (openapi-typescript + openapi-fetch + react-query) + partial MSW mocks. Two commits.`         | Infrastructure |
| 3   | `Build the app shell (sidebar 80px + header 64px + footer folio + theme toggle + routing scaffold). Single commit.` | Shell          |
| 4   | `Build P1 login + P2 dashboard following the reference image structure exactly. Two commits.`                       | Pages 1-2      |
| 5   | `Build P3 hypervisors + P4 new hypervisor. Two commits.`                                                            | Pages 3-4      |
| 6   | `Build P5 vms + P6 migrations list. Two commits.`                                                                   | Pages 5-6      |
| 7   | `/effort high` then `Build P7 migration detail. Single commit.`                                                     | Page 7         |
| 8   | `/effort medium` then `Build P8 settings + readme. Two commits.`                                                    | Final          |

**`/clear` between every line.** Re-set `/model opusplan` and `/effort medium` after each clear if they don't persist.

---

# How to attach the image to your Claude Code message

In the Claude Code terminal, you have two options depending on your version:

**Option A** — drag and drop the image file directly into the terminal window. It shows as `[Image #1]` in your message.

**Option B** — type `/image` and paste from clipboard, or specify a file path.

If neither works in your version, use `claude --image path/to/image.png` when launching, OR open the Claude Code web UI if available.

After attaching, paste the prompt above. The image is the visual reference for the brutalist console direction.
