import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "react-hot-toast";
import { router } from "./routes";
import { queryClient } from "./lib/queryClient";
import { registerSessionNavigator } from "./lib/session";
import { AuthGate } from "./app/AuthGate";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./index.css";

// Give `forceLogout` (in lib/session, reachable from the axios interceptor)
// an imperative way to redirect to /login. The router cannot be imported
// directly by lib/session without forming an init cycle, so it is injected
// here at startup instead.
registerSessionNavigator((path) => {
  void router.navigate(path);
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthGate>
          <RouterProvider router={router} />
        </AuthGate>
        <Toaster
          position="bottom-right"
          toastOptions={{
            style: {
              background: "var(--card-gradient)",
              backdropFilter: "blur(60px)",
              WebkitBackdropFilter: "blur(60px)",
              color: "var(--text-primary)",
              border: "1px solid var(--hairline)",
              borderRadius: "14px",
              fontFamily: "var(--font-sans)",
              fontSize: "13px",
              fontWeight: 500,
              letterSpacing: "0",
              boxShadow: "var(--shadow-card)",
              padding: "12px 16px",
            },
            success: {
              iconTheme: {
                primary: "var(--alert-success-light)",
                secondary: "var(--bg-app)",
              },
            },
            error: {
              iconTheme: {
                primary: "var(--alert-critical)",
                secondary: "var(--bg-app)",
              },
            },
          }}
        />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
