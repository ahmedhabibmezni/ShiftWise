import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "react-hot-toast";
import { router } from "./routes";
import { queryClient } from "./lib/queryClient";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: "var(--bg-elev)",
            color: "var(--ink)",
            border: "1px solid var(--line-strong)",
            borderRadius: "2px",
            fontFamily: "var(--font-mono, monospace)",
            fontSize: "12px",
            letterSpacing: "0.02em",
          },
        }}
      />
    </QueryClientProvider>
  </StrictMode>,
);
