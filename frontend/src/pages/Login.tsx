import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { AxiosError } from "axios";
import { z } from "zod";
import { ArrowRight, Layers, LockKeyhole, Shield } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { LiveIndicator } from "@/components/ui/LiveIndicator";
import { Callout } from "@/components/ui/Callout";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { login as loginRequest, fetchCurrentUser } from "@/api/auth";
import { setAccessToken, useAuthStore } from "@/store/auth";
import { queryClient } from "@/lib/queryClient";
import { describeErrorOrNull } from "@/lib/errors";

const loginSchema = z.object({
  email: z.string().min(1, "Email is required").email("Invalid email address"),
  password: z.string().min(1, "Password is required"),
});

type LoginFormValues = z.infer<typeof loginSchema>;
type LocationState = { from?: string };

const GENERIC_LOGIN_ERROR = "Login failed. Check your credentials.";

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const setSession = useAuthStore((s) => s.setSession);
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  const mutation = useMutation({
    mutationFn: async (values: LoginFormValues) => {
      const tokens = await loginRequest(values);
      // The axios interceptor reads the access token from the store on each
      // request. Set it before /me so a fresh session (no refresh cookie)
      // succeeds — otherwise FastAPI's HTTPBearer returns 403 and the
      // response interceptor only retries on 401.
      setAccessToken(tokens.access_token);
      const me = await fetchCurrentUser();
      return { tokens, me };
    },
    onSuccess: ({ tokens, me }) => {
      // Drop any cached queries before the new session is established. On a
      // same-tab account switch (sign out, then sign in as a different
      // user) the prior tenant's VMs/migrations/stats would otherwise
      // remain in the TanStack cache and flash on the next screen.
      queryClient.clear();
      setSession(tokens.access_token, me);
      const target = (location.state as LocationState | null)?.from ?? "/";
      navigate(target, { replace: true });
    },
    onError: (err) => {
      const status = (err as AxiosError).response?.status;
      const detail = describeErrorOrNull(err);

      if (status === 403) {
        const msg =
          detail ?? "Your account is inactive. Contact an administrator to reactivate it.";
        setFormError(msg);
        toast.error(msg);
        return;
      }
      if (status === 401) {
        setFormError(GENERIC_LOGIN_ERROR);
        return;
      }
      const msg = detail ?? "Network error. Try again.";
      setFormError(msg);
      toast.error(msg);
    },
  });

  const onSubmit = (values: LoginFormValues) => {
    setFormError(null);
    mutation.mutate(values);
  };

  return (
    <div className="min-h-[100dvh] w-full grid grid-cols-1 lg:grid-cols-[1.05fr_1fr] relative overflow-hidden">
      <BrandPanel />

      <section className="relative flex items-center justify-center px-6 py-12">
        <div className="absolute top-6 right-6">
          <ThemeToggle />
        </div>
        <div className="glass-card w-full max-w-[440px] p-8">
          <header className="mb-7">
            <span
              aria-hidden
              className="icon-container icon-container--accent w-12 h-12 rounded-2xl mb-5"
            >
              <Layers size={22} strokeWidth={2} />
            </span>
            <div className="kicker mb-2">Console · Authentication</div>
            <h1 className="text-[28px] font-bold tracking-[-0.02em] leading-[1.1] text-[var(--text-primary)]">
              Welcome back
            </h1>
            <p className="mt-2 text-[13px] text-[var(--text-secondary)] leading-relaxed">
              Operator access · audit logged · HttpOnly cookie with rotating refresh token.
            </p>
          </header>

          <form
            onSubmit={handleSubmit(onSubmit)}
            noValidate
            aria-label="Login form"
            className="space-y-5"
          >
            <Field
              id="email"
              label="Email"
              type="email"
              autoComplete="email"
              autoFocus
              error={errors.email?.message}
              register={register("email")}
            />

            <Field
              id="password"
              label="Password"
              type="password"
              autoComplete="current-password"
              error={errors.password?.message}
              register={register("password")}
            />

            {formError && (
              <Callout tone="err" role="alert">
                {formError}
              </Callout>
            )}

            <Button
              type="submit"
              variant="primary"
              loading={isSubmitting || mutation.isPending}
              trailingIcon={<Icon icon={ArrowRight} size={16} />}
              className="w-full h-11"
            >
              Sign in
            </Button>
          </form>

          <footer className="mt-7 flex items-center justify-between gap-4 pt-5 border-t border-[var(--hairline)]">
            <span className="flex items-center gap-2 text-[10px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
              <Icon icon={LockKeyhole} size={12} /> TLS 1.3 · HSTS
            </span>
            <span className="flex items-center gap-2 text-[10px] uppercase tracking-[0.04em] font-bold text-[var(--text-muted)]">
              <Icon icon={Shield} size={12} /> OAuth 2.1 BCP
            </span>
          </footer>
        </div>
      </section>
    </div>
  );
}

function Field({
  id,
  label,
  type,
  autoComplete,
  autoFocus,
  error,
  register,
}: {
  id: string;
  label: string;
  type: string;
  autoComplete: string;
  autoFocus?: boolean;
  error?: string;
  register: ReturnType<ReturnType<typeof useForm>["register"]>;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="block text-[12px] font-bold uppercase tracking-[0.04em] text-[var(--text-secondary)] mb-1.5"
      >
        {label}
      </label>
      <Input
        id={id}
        type={type}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        invalid={!!error}
        aria-describedby={error ? `${id}-error` : undefined}
        className="h-11"
        {...register}
      />
      {error && (
        <div
          id={`${id}-error`}
          role="alert"
          className="mt-1.5 text-[12px] text-[var(--alert-critical)]"
        >
          {error}
        </div>
      )}
    </div>
  );
}

function BrandPanel() {
  return (
    <aside className="relative hidden lg:flex flex-col justify-between p-12 overflow-hidden">
      {/* Decorative orbital SVG, top-right */}

      <header className="relative flex items-center gap-3">
        <span
          aria-hidden
          className="icon-container icon-container--accent w-11 h-11 rounded-xl"
        >
          <Layers size={22} strokeWidth={2} />
        </span>
        <div className="flex flex-col leading-none gap-1">
          <span className="text-[14px] font-bold tracking-[0.02em] text-[var(--text-primary)]">
            ShiftWise
          </span>
          <span className="text-[10px] font-medium uppercase tracking-[0.06em] text-[var(--text-muted)]">
            VM Migration Platform · v2.4.1
          </span>
        </div>
      </header>

      <div className="relative max-w-[44ch]">
        <div className="kicker mb-3">Manifesto · 01</div>
        <p
          className="text-[40px] font-bold leading-[1.05] tracking-[-0.025em] text-[var(--text-primary)]"
          style={{ textWrap: "balance" } as React.CSSProperties}
        >
          A fleet to migrate.
          <br />
          <span className="text-[var(--accent-light)]">A cluster to master.</span>
          <br />
          A pipeline to orchestrate.
        </p>
        <p className="mt-6 text-[13px] text-[var(--text-secondary)] max-w-[52ch] leading-relaxed">
          Discovery · Analyzer · Converter · Adapter · Migrator · Reporting. Every VM transits six stages before landing on OpenShift Virtualization.
        </p>
      </div>

      <footer className="relative flex items-center justify-between text-[12px] text-[var(--text-secondary)]">
        <div className="flex items-center gap-2">
          <LiveIndicator label={null} srLabel="Cluster online" tone="ok" />
          <span>Cluster OK · 3 masters · KubeVirt v1.4.1</span>
        </div>
        <span className="text-[var(--text-muted)]">© 2026 · NextStep-IT</span>
      </footer>
    </aside>
  );
}
