import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { AxiosError } from "axios";
import { z } from "zod";
import { ArrowRight, LockKeyhole, Shield } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Icon } from "@/components/ui/Icon";
import { LiveIndicator } from "@/components/ui/LiveIndicator";
import { Callout } from "@/components/ui/Callout";
import { login as loginRequest, fetchCurrentUser } from "@/api/auth";
import { useAuthStore } from "@/store/auth";
import type { ApiError } from "@/api/types";

const loginSchema = z.object({
  email: z.string().min(1, "email required").email("invalid email"),
  password: z.string().min(1, "password required"),
});

type LoginFormValues = z.infer<typeof loginSchema>;
type LocationState = { from?: string };

const GENERIC_LOGIN_ERROR = "login failed. check your credentials.";

function extractDetail(err: unknown): string | null {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    if (data?.detail) return data.detail;
  }
  return null;
}

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
      const me = await fetchCurrentUser();
      return { tokens, me };
    },
    onSuccess: ({ tokens, me }) => {
      setSession(tokens.access_token, me);
      const target = (location.state as LocationState | null)?.from ?? "/";
      navigate(target, { replace: true });
    },
    onError: (err) => {
      const status = (err as AxiosError).response?.status;
      const detail = extractDetail(err);

      if (status === 403) {
        const msg = detail ?? "account inactive.";
        setFormError(msg);
        toast.error(msg);
        return;
      }
      if (status === 401) {
        setFormError(GENERIC_LOGIN_ERROR);
        return;
      }
      const msg = detail ?? "network error. try again.";
      setFormError(msg);
      toast.error(msg);
    },
  });

  const onSubmit = (values: LoginFormValues) => {
    setFormError(null);
    mutation.mutate(values);
  };

  return (
    <div className="min-h-[100dvh] w-full bg-bg text-ink grid grid-cols-1 lg:grid-cols-[1.05fr_1fr] relative overflow-hidden">
      <span aria-hidden className="sw-grain" />
      <BrandPanel />

      <section className="relative z-[2] flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-[400px]">
          <header className="mb-8">
            <div className="kicker mb-2">console · authentication</div>
            <h1 className="text-h1 lowercase leading-none">
              welcome back<span className="sw-caret" />
            </h1>
            <p className="mt-2 font-mono text-[12px] text-ink-muted leading-relaxed">
              operator access · audit logged · httponly cookie + rotating refresh token
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
              label="email"
              type="email"
              autoComplete="email"
              autoFocus
              error={errors.email?.message}
              register={register("email")}
            />

            <Field
              id="password"
              label="password"
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
              uppercase
              loading={isSubmitting || mutation.isPending}
              trailingIcon={<Icon icon={ArrowRight} size={16} />}
              className="w-full h-11"
            >
              log in
            </Button>
          </form>

          <footer className="mt-8 flex items-center justify-between gap-4">
            <span className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.08em] text-ink-faint">
              <Icon icon={LockKeyhole} size={11} /> tls 1.3 · hsts
            </span>
            <span className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.08em] text-ink-faint">
              <Icon icon={Shield} size={11} /> oauth 2.1 bcp
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
        className="block font-mono text-[10px] uppercase tracking-[0.08em] text-ink-muted mb-2"
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
          className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.04em] text-err"
        >
          {error}
        </div>
      )}
    </div>
  );
}

function BrandPanel() {
  return (
    <aside className="relative hidden lg:flex flex-col justify-between bg-bg-elev p-12 overflow-hidden border-r border-line">
      <span aria-hidden className="sw-hairlines absolute inset-0 opacity-30" />
      <span
        aria-hidden
        className="absolute -top-32 -right-32 h-[480px] w-[480px] rounded-full bg-signal/8 blur-3xl"
      />

      <header className="relative z-[2] flex items-center gap-3">
        <span
          aria-hidden
          className="relative inline-flex h-10 w-10 items-center justify-center bg-signal text-signal-ink font-mono font-bold text-[14px]"
        >
          SW
          <span aria-hidden className="absolute -bottom-1.5 -right-1.5 h-2.5 w-2.5 bg-bg-elev border border-line-strong" />
        </span>
        <div className="flex flex-col leading-none">
          <span className="font-mono text-[13px] font-semibold tracking-[0.08em] text-ink">
            SHIFTWISE
          </span>
          <span className="font-mono text-[10px] uppercase tracking-[0.1em] text-ink-muted mt-1">
            vm migration platform · v2.4.1
          </span>
        </div>
      </header>

      <div className="relative z-[2] max-w-[44ch]">
        <div className="kicker mb-3">manifesto · 01</div>
        <p className="text-h1 lowercase leading-[1.1] text-ink" style={{ textWrap: "balance" }}>
          a fleet to migrate.
          <br />
          <span className="text-signal">a cluster to master.</span>
          <br />
          a pipeline to orchestrate.
        </p>
        <p className="mt-6 font-mono text-[12px] text-ink-muted max-w-[52ch] leading-relaxed">
          discovery · analyzer · converter · adapter · migrator · reporting. every vm transits six stages before landing on openshift virtualization.
        </p>
      </div>

      <footer className="relative z-[2] flex items-center justify-between font-mono text-[10px] uppercase tracking-[0.08em] text-ink-muted">
        <div className="flex items-center gap-2">
          <LiveIndicator label={null} srLabel="Cluster online" tone="ok" />
          <span>cluster ok · 3 masters · kubevirt v1.4.1</span>
        </div>
        <span className="text-ink-faint">© 2026 · nextstep-it</span>
      </footer>
    </aside>
  );
}
