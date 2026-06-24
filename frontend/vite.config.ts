import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { execSync } from "node:child_process";

function gitShortHash(): string {
  try {
    return execSync("git rev-parse --short HEAD").toString().trim();
  } catch {
    return "unknown";
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  define: {
    __BUILD_HASH__: JSON.stringify(gitShortHash()),
    __BUILD_DATE__: JSON.stringify(new Date().toISOString().slice(0, 10)),
  },
  build: {
    rollupOptions: {
      output: {
        // Split node_modules into stable, cacheable vendor chunks so the
        // initial bundle stays under Vite's 500 kB chunk-size warning and a
        // dependency bump only invalidates its own chunk. React and its
        // tightly-coupled consumers (router, forms, store) stay together to
        // avoid any dual-React context hazard.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (
            /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|react-hook-form|@hookform|zustand)[\\/]/.test(
              id,
            )
          ) {
            return "vendor-react";
          }
          if (id.includes("@tanstack")) return "vendor-query";
          if (id.includes("lucide-react")) return "vendor-icons";
          if (/[\\/]node_modules[\\/](date-fns|zod|axios|clsx|tailwind-merge)[\\/]/.test(id)) {
            return "vendor-utils";
          }
          return "vendor";
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        cookieDomainRewrite: "localhost",
        cookiePathRewrite: { "/api/v1/auth": "/api/v1/auth" },
      },
    },
  },
});
