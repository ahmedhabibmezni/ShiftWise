# 🖥 ShiftWise Frontend

[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Vite](https://img.shields.io/badge/Vite-7.2-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4.1-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)

> **🚧 Status: In Development** — Project scaffold initialized, core views not yet implemented.

The ShiftWise frontend is a **React Single Page Application** built with TypeScript, Vite, and Tailwind CSS. It provides an interactive dashboard for managing VM-to-OpenShift migrations with real-time monitoring via WebSocket.

---

## 📁 Project Structure

```
frontend/
├── public/                     # Static assets
├── src/
│   ├── assets/                 # Images, icons
│   ├── App.tsx                 # Root application component
│   ├── App.css                 # App-level styles
│   ├── main.tsx                # Entry point (ReactDOM render)
│   └── index.css               # Global CSS (Tailwind directives)
├── index.html                  # HTML template
├── package.json                # Dependencies and scripts
├── tsconfig.json               # TypeScript base config
├── tsconfig.app.json           # App-specific TS config
├── tsconfig.node.json          # Node/Vite TS config
├── vite.config.ts              # Vite configuration
└── eslint.config.js            # ESLint configuration
```

---

## 🚀 Setup

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint
npm run lint
```

The dev server runs at `http://localhost:5173` by default.

---

## 🛠 Tech Stack

| Package | Version | Purpose |
|---------|---------|---------|
| `react` | 19.2 | UI component library |
| `react-dom` | 19.2 | DOM rendering |
| `react-router-dom` | 7.13 | Client-side routing |
| `typescript` | 5.9 | Type safety |
| `vite` | 7.2 | Build tool & dev server |
| `tailwindcss` | 4.1 | Utility-first CSS framework |
| `@tanstack/react-query` | 5.x | Server state management (API data fetching) |
| `@tanstack/react-table` | 8.x | Headless data table engine |
| `zustand` | 5.x | Lightweight client state management |
| `axios` | 1.13 | HTTP client for API calls |
| `socket.io-client` | 4.8 | WebSocket client for real-time updates |
| `recharts` | 3.7 | Chart/graph rendering |
| `react-hook-form` | 7.71 | Performant form handling |
| `zod` | 4.3 | Schema-based form validation |
| `lucide-react` | 0.563 | Icon library |
| `react-hot-toast` | 2.6 | Toast notifications |
| `date-fns` | 4.1 | Date formatting utilities |

---

## 🚧 Planned Views

### Dashboard
- Migration status overview (success/failure/in-progress counts)
- Active migration monitoring with real-time status updates
- VM inventory summary charts (by hypervisor, by compatibility)

### Migration Wizard
- Step-by-step migration workflow:
  1. Select source VMs
  2. Review compatibility analysis
  3. Choose migration strategy (direct / conversion / alternative)
  4. Configure target namespace and resources
  5. Execute and monitor

### VM Inventory
- Data table with filtering, sorting, and pagination
- Compatibility status indicators (green/yellow/red)
- Drill-down to individual VM details

### Compatibility Report
- Detailed analysis results per VM
- Categorized issues list with remediation suggestions
- Export report (PDF/CSV)

### Migration Logs
- Real-time log stream via WebSocket
- Per-migration event timeline
- Error details with stack traces

### Administration
- User management (CRUD)
- Role management with permission editor
- Hypervisor connection management
- System settings

---

## 🔌 API Integration

The frontend communicates with the backend via:

| Protocol | Purpose | Library |
|----------|---------|---------|
| REST (HTTPS) | CRUD operations, auth, data queries | `axios` + `@tanstack/react-query` |
| WebSocket (WSS) | Real-time migration status, log streaming | `socket.io-client` |

### API Base URL Configuration

```typescript
// Configured via environment variable
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';
```

### Authentication Flow

1. User submits credentials → `POST /api/v1/auth/login`
2. Store JWT in memory (Zustand) — not localStorage (XSS mitigation)
3. Attach `Authorization: Bearer <token>` header to all API requests via Axios interceptor
4. Auto-refresh token before expiry using the refresh endpoint