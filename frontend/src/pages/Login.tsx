import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import toast from "react-hot-toast";
import { AxiosError } from "axios";
import { z } from "zod";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { login as loginRequest, fetchCurrentUser } from "@/api/auth";
import { useAuthStore } from "@/store/auth";
import type { ApiError } from "@/api/types";

const loginSchema = z.object({
  email: z.string().min(1, "Email requis").email("Email invalide"),
  password: z.string().min(1, "Mot de passe requis"),
});

type LoginFormValues = z.infer<typeof loginSchema>;

type LocationState = { from?: string };

const GENERIC_LOGIN_ERROR = "Échec de la connexion. Vérifiez vos identifiants.";

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
        const msg = detail ?? "Compte inactif.";
        setFormError(msg);
        toast.error(msg);
        return;
      }
      if (status === 401) {
        setFormError(GENERIC_LOGIN_ERROR);
        return;
      }
      const msg = detail ?? "Erreur réseau. Réessayez.";
      setFormError(msg);
      toast.error(msg);
    },
  });

  const onSubmit = (values: LoginFormValues) => {
    setFormError(null);
    mutation.mutate(values);
  };

  return (
    <div className="min-h-screen w-full bg-bg text-ink flex items-center justify-center px-4">
      <div className="w-full max-w-[380px]">
        <header className="mb-6">
          <div className="font-mono font-bold text-[28px] tracking-[0.04em] text-ink leading-none">
            SW · SHIFTWISE
          </div>
          <div className="mt-2 font-mono text-[11px] uppercase tracking-[0.06em] text-ink-muted">
            console · authentification
          </div>
        </header>

        <form
          onSubmit={handleSubmit(onSubmit)}
          noValidate
          aria-label="Formulaire de connexion"
          className="border border-line-strong bg-bg-elev p-6 space-y-4"
        >
          <div>
            <label
              htmlFor="email"
              className="block font-mono text-[10px] uppercase tracking-[0.06em] text-ink-muted mb-1.5"
            >
              email
            </label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              autoFocus
              invalid={!!errors.email}
              aria-describedby={errors.email ? "email-error" : undefined}
              {...register("email")}
            />
            {errors.email && (
              <div
                id="email-error"
                role="alert"
                className="mt-1 font-mono text-[10px] uppercase tracking-[0.04em] text-err"
              >
                {errors.email.message}
              </div>
            )}
          </div>

          <div>
            <label
              htmlFor="password"
              className="block font-mono text-[10px] uppercase tracking-[0.06em] text-ink-muted mb-1.5"
            >
              password
            </label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              invalid={!!errors.password}
              aria-describedby={errors.password ? "password-error" : undefined}
              {...register("password")}
            />
            {errors.password && (
              <div
                id="password-error"
                role="alert"
                className="mt-1 font-mono text-[10px] uppercase tracking-[0.04em] text-err"
              >
                {errors.password.message}
              </div>
            )}
          </div>

          {formError && (
            <div
              role="alert"
              className="border border-err text-err bg-bg-elev-2 px-3 py-2 font-mono text-[11px] uppercase tracking-[0.04em]"
            >
              {formError}
            </div>
          )}

          <Button
            type="submit"
            variant="primary"
            uppercase
            loading={isSubmitting || mutation.isPending}
            className="w-full"
          >
            connexion
          </Button>
        </form>

        <footer className="mt-4 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-muted">
          session refresh · cookie httponly
        </footer>
      </div>
    </div>
  );
}
