import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

type Props = {
  children: ReactNode;
  /** Optional custom fallback. Receives a reset callback to retry rendering. */
  fallback?: (reset: () => void) => ReactNode;
};

type State = {
  error: Error | null;
};

/**
 * Top-level React error boundary.
 *
 * A render-phase exception anywhere below this component would otherwise
 * unmount the whole React tree and leave the user staring at a blank page.
 * This boundary catches it, shows a recoverable fallback, and lets the user
 * retry without a full browser reload.
 *
 * Scope: render errors only. Async errors (event handlers, effects,
 * rejected promises) are not caught by error boundaries — those surface
 * through the axios interceptor and react-hot-toast instead.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Keep a console trace for diagnostics. A real telemetry sink (Sentry,
    // etc.) would hook in here — out of scope for now.
    console.error("Unhandled render error:", error, info.componentStack);
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (error === null) return this.props.children;

    if (this.props.fallback) return this.props.fallback(this.reset);

    return (
      <div
        role="alert"
        className="min-h-[100dvh] flex items-center justify-center p-6"
      >
        <div className="glass-card max-w-md p-7">
          <div className="kicker mb-2">Something went wrong</div>
          <h1 className="text-[18px] font-bold tracking-[-0.01em] text-[var(--text-primary)]">
            This page hit an unexpected error
          </h1>
          <p className="mt-2 text-[13px] leading-relaxed text-[var(--text-secondary)]">
            The interface caught a rendering fault and stopped to avoid a
            blank screen. Retrying re-renders the page; if it keeps failing,
            reload the browser.
          </p>
          <div className="mt-5 flex items-center gap-2.5">
            <button
              type="button"
              onClick={this.reset}
              className="h-10 px-4 rounded-[12px] text-[13px] font-semibold text-white border border-transparent shadow-[var(--shadow-accent)] transition-all duration-200 hover:brightness-110 active:brightness-95"
              style={{
                background:
                  "linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-light) 100%)",
              }}
            >
              Try again
            </button>
            <button
              type="button"
              onClick={() => window.location.assign("/")}
              className="h-10 px-4 rounded-[12px] text-[13px] font-semibold glass-card text-[var(--text-primary)] transition-all duration-200 hover:bg-[var(--surface-soft-strong)]"
            >
              Go to dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }
}
