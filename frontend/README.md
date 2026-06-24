# 🖥 ShiftWise Frontend

[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Vite](https://img.shields.io/badge/Vite-7.2-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4.1-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)

> **🚧 Status: In Progress** — all core pages are built; integration and polish are ongoing.

The ShiftWise frontend is a **React 19 single-page application** built with TypeScript, Vite, and Tailwind CSS. It provides the dashboard and management UI for VM-to-OpenShift migrations.

---

## 📁 Project Structure

```
frontend/
├── public/                     # Static assets
├── src/
│   ├── api/                    # Typed API client modules (axios), one per resource
│   ├── app/                    # AppLayout + AuthGate
│   ├── components/
│   │   ├── shell/              # Header, Sidebar, Footer, CommandPalette
│   │   └── ui/                 # Reusable UI component library
│   ├── hooks/                  # Custom React hooks
│   ├── lib/                    # axios instance, query client, formatting helpers
│   ├── pages/                  # Route pages + slide-over drawers
│   ├── routes/                 # Route guards (ProtectedRoute, PublicOnlyRoute)
│   ├── store/                  # Zustand stores (auth)
│   ├── styles/                 # Design tokens + base styles
│   ├── test/                   # Vitest setup + MSW handlers
│   ├── routes.tsx              # Router configuration
│   ├── main.tsx                # Entry point (ReactDOM render)
│   └── index.css               # Global CSS (Tailwind directives)
├── index.html                  # HTML template
├── package.json                # Dependencies and scripts
├── tsconfig*.json               # TypeScript configuration
├── vite.config.ts               # Vite configuration
└── eslint.config.js             # ESLint configuration
```

---

## 🚀 Setup

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production (type-check + bundle)
npm run build

# Preview production build
npm run preview

# Lint
npm run lint

# Run tests
npm run test
```

The dev server runs at `http://localhost:5173` and proxies API calls to the backend at `http://localhost:8000`.

---

## 🛠 Tech Stack

| Package | Version | Purpose |
|---------|---------|---------|
| `react` / `react-dom` | 19.2 | UI framework |
| `typescript` | 5.9 | Type safety |
| `vite` | 7.2 | Build tool & dev server |
| `tailwindcss` | 4.1 | Utility-first CSS (`@tailwindcss/vite`) |
| `react-router-dom` | 7.13 | Client-side routing |
| `@tanstack/react-query` | 5.x | Server state management (with polling) |
| `zustand` | 5.x | Client state management (auth, UI) |
| `axios` | 1.13 | HTTP client with JWT refresh interceptor |
| `react-hook-form` + `@hookform/resolvers` | 7.x | Form handling |
| `zod` | 4.x | Schema-based validation |
| `lucide-react` | 0.563 | Icon set |
| `react-hot-toast` | 2.6 | Toast notifications |
| `clsx` + `tailwind-merge` | — | `className` composition |
| `@fontsource/plus-jakarta-sans` | — | Bundled font |
| `vitest` + `msw` | 4.x / 2.x | Unit testing + API mocking (dev) |

---

## 📄 Pages

| Route | Page | Description |
|-------|------|-------------|
| `/login` | Login | Authentication |
| `/` | Dashboard | KPIs, migration queue, activity feed, compatibility distribution |
| `/hypervisors` | Hypervisors | Hypervisor list + create / detail drawers |
| `/vms` | VMs | VM inventory + compatibility analysis drawer |
| `/migrations` | Migrations | Migration list + create / detail drawers |
| `/reports` | Reports | Migration history with CSV export |
| `/users` | Users | User management (admin) |
| `/roles` | Roles | Role and permission management (admin) |
| `/settings` | Settings | Profile and preferences |
| `/styleguide` | Styleguide | Component / design-system reference |

Routes are defined in `src/routes.tsx`. `ProtectedRoute` and `PublicOnlyRoute` guard authenticated vs. public access.

---

## 🔌 API Integration

The frontend communicates with the backend over **REST (HTTPS)** using `axios` and `@tanstack/react-query`.

- Server state is fetched and cached with TanStack Query.
- Live migration and conversion progress is updated by **polling** (`refetchInterval`) — there is no WebSocket channel.
- `msw` (Mock Service Worker) provides API mocks for tests and offline development.

### API Base URL Configuration

```typescript
// Configured via environment variable, with a dev default
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
```

### Authentication Flow

1. User submits credentials → `POST /api/v1/auth/login`.
2. The access token is held in memory (Zustand store) — not in `localStorage` (XSS mitigation).
3. An Axios request interceptor attaches `Authorization: Bearer <token>` to API calls.
4. On a `401`, the Axios interceptor calls `POST /api/v1/auth/refresh` — the refresh token travels as an `HttpOnly` cookie — then retries the original request.
5. Logout calls `POST /api/v1/auth/logout`, which revokes the refresh-token family.
