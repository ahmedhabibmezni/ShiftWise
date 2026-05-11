import { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { AxiosError } from "axios";
import { KeyRound, Save, UserCog } from "lucide-react";
import toast from "react-hot-toast";
import { z } from "zod";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Panel } from "@/components/ui/Panel";
import { PageHeader } from "@/components/ui/PageHeader";
import { RoleBadge } from "@/components/ui/RoleBadge";
import { updateUser, type UpdateUserPayload } from "@/api/users";
import type { ApiError, User } from "@/api/types";
import { primaryRole } from "@/lib/permissions";
import { useAuthStore } from "@/store/auth";

function describeError(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    if (data?.detail) return data.detail;
  }
  return fallback;
}

const profileSchema = z.object({
  email: z.string().email("invalid email").max(255),
  username: z
    .string()
    .min(3, "min 3 characters")
    .max(100)
    .regex(/^[a-zA-Z][a-zA-Z0-9._-]*$/, "must start with a letter — letters, digits, . _ -"),
  first_name: z.string().max(100).optional().or(z.literal("")),
  last_name: z.string().max(100).optional().or(z.literal("")),
});
type ProfileValues = z.infer<typeof profileSchema>;

// Mirror of the backend UserUpdate.password validator. Replicating it here
// turns a 400 round-trip into an inline error.
const passwordSchema = z
  .object({
    current_password: z.string().min(1, "required"),
    new_password: z
      .string()
      .min(8, "min 8 characters")
      .regex(/[A-Z]/, "must contain an uppercase letter")
      .regex(/[a-z]/, "must contain a lowercase letter")
      .regex(/\d/, "must contain a digit")
      .regex(/[!@#$%^&*(),.?":{}|<>]/, "must contain a special character"),
    confirm: z.string().min(1, "required"),
  })
  .refine((v) => v.new_password === v.confirm, {
    message: "passwords do not match",
    path: ["confirm"],
  })
  .refine((v) => v.current_password !== v.new_password, {
    message: "new password must differ from the current one",
    path: ["new_password"],
  });
type PasswordValues = z.infer<typeof passwordSchema>;

export default function Settings() {
  const user = useAuthStore((s) => s.user);

  if (!user) {
    return (
      <div className="max-w-[1440px] mx-auto p-6 md:p-8">
        <Callout tone="err">unable to load your account — please log in again.</Callout>
      </div>
    );
  }

  return (
    <div className="max-w-[960px] mx-auto p-6 md:p-8 space-y-6">
      <PageHeader
        kicker="system"
        title="settings"
        breadcrumbs={[{ label: "console" }, { label: "system" }, { label: "settings" }]}
        description="Your account, credentials, and session-scoped preferences."
      />

      <IdentityCard user={user} />
      <ProfileSection user={user} />
      <PasswordSection user={user} />
    </div>
  );
}

/* ------------------------------- identity --------------------------------- */

function IdentityCard({ user }: { user: User }) {
  const role = primaryRole(user) ?? "member";
  return (
    <Panel density="compact" kicker="signed in as" title={user.full_name || user.username}>
      <div className="flex items-center gap-3 flex-wrap mt-2">
        <RoleBadge role={role} />
        <Badge variant={user.is_active ? "ok" : "neutral"}>
          {user.is_active ? "active" : "inactive"}
        </Badge>
        {user.is_verified && <Badge variant="info">verified</Badge>}
        <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-ink-muted">
          tenant · {user.tenant_id}
        </span>
      </div>
    </Panel>
  );
}

/* ------------------------------- profile --------------------------------- */

function ProfileSection({ user }: { user: User }) {
  const queryClient = useQueryClient();
  const setUser = useAuthStore((s) => s.setUser);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty, isSubmitting },
  } = useForm<ProfileValues>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      email: user.email,
      username: user.username,
      first_name: user.first_name ?? "",
      last_name: user.last_name ?? "",
    },
  });

  // Backfill from the live user every time it changes — covers the case
  // where the user object refreshes (e.g. /me reload after re-login) so
  // the form does not silently keep stale defaults.
  useEffect(() => {
    reset({
      email: user.email,
      username: user.username,
      first_name: user.first_name ?? "",
      last_name: user.last_name ?? "",
    });
  }, [user.id, user.email, user.username, user.first_name, user.last_name, reset]);

  const mutation = useMutation({
    mutationFn: (values: ProfileValues) => {
      const payload: UpdateUserPayload = {};
      if (values.email !== user.email) payload.email = values.email;
      if (values.username !== user.username) payload.username = values.username.toLowerCase();
      if (values.first_name !== (user.first_name ?? "")) {
        payload.first_name = values.first_name || null;
      }
      if (values.last_name !== (user.last_name ?? "")) {
        payload.last_name = values.last_name || null;
      }
      if (Object.keys(payload).length === 0) {
        return Promise.resolve(user);
      }
      return updateUser(user.id, payload);
    },
    onSuccess: (next) => {
      toast.success("profile saved");
      // Reflect the change in the auth store + any cached /me query so the
      // sidebar/RoleStripe/header pick it up without a hard refresh.
      setUser(next);
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      queryClient.invalidateQueries({ queryKey: ["users"] });
      reset({
        email: next.email,
        username: next.username,
        first_name: next.first_name ?? "",
        last_name: next.last_name ?? "",
      });
    },
    onError: (err) => toast.error(describeError(err, "save failed")),
  });

  const onSubmit: SubmitHandler<ProfileValues> = (values) => mutation.mutate(values);

  return (
    <Panel
      kicker="profile"
      title="account details"
      action={<Icon icon={UserCog} size={16} className="text-ink-faint" />}
    >
      <form
        id="settings-profile-form"
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="space-y-4 mt-2"
      >
        <Field id="set-email" label="email" error={errors.email?.message}>
          <Input
            id="set-email"
            type="email"
            autoComplete="email"
            invalid={!!errors.email}
            {...register("email")}
          />
        </Field>

        <Field id="set-username" label="username" error={errors.username?.message}>
          <Input
            id="set-username"
            autoComplete="username"
            invalid={!!errors.username}
            {...register("username")}
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field id="set-first" label="first name" error={errors.first_name?.message}>
            <Input
              id="set-first"
              autoComplete="given-name"
              invalid={!!errors.first_name}
              {...register("first_name")}
            />
          </Field>
          <Field id="set-last" label="last name" error={errors.last_name?.message}>
            <Input
              id="set-last"
              autoComplete="family-name"
              invalid={!!errors.last_name}
              {...register("last_name")}
            />
          </Field>
        </div>

        <div className="flex items-center justify-end pt-2">
          <Button
            type="submit"
            variant="primary"
            uppercase
            loading={isSubmitting || mutation.isPending}
            disabled={!isDirty}
            leadingIcon={<Icon icon={Save} size={14} />}
          >
            save profile
          </Button>
        </div>
      </form>
    </Panel>
  );
}

/* ------------------------------- password --------------------------------- */

function PasswordSection({ user }: { user: User }) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<PasswordValues>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { current_password: "", new_password: "", confirm: "" },
  });

  const mutation = useMutation({
    mutationFn: (values: PasswordValues) =>
      // Backend doesn't take current_password — we ask for it anyway as a
      // local sanity check (user shouldn't rotate while shoulder-surfed).
      // The check stays client-side: if the current password is wrong, the
      // backend won't notice; only the new password is shipped.
      updateUser(user.id, { password: values.new_password }),
    onSuccess: () => {
      toast.success("password updated · keep it safe");
      reset();
    },
    onError: (err) => toast.error(describeError(err, "password update failed")),
  });

  const onSubmit: SubmitHandler<PasswordValues> = (values) => mutation.mutate(values);

  return (
    <Panel
      kicker="security"
      title="change password"
      action={<Icon icon={KeyRound} size={16} className="text-ink-faint" />}
    >
      <Callout tone="info" className="mt-2">
        rotate periodically · 8+ chars · upper + lower + digit + special.
      </Callout>

      <form
        id="settings-password-form"
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="space-y-4 mt-4"
      >
        <Field
          id="set-current"
          label="current password"
          error={errors.current_password?.message}
        >
          <Input
            id="set-current"
            type="password"
            autoComplete="current-password"
            invalid={!!errors.current_password}
            {...register("current_password")}
          />
        </Field>

        <Field
          id="set-new"
          label="new password"
          error={errors.new_password?.message}
        >
          <Input
            id="set-new"
            type="password"
            autoComplete="new-password"
            invalid={!!errors.new_password}
            {...register("new_password")}
          />
        </Field>

        <Field id="set-confirm" label="confirm" error={errors.confirm?.message}>
          <Input
            id="set-confirm"
            type="password"
            autoComplete="new-password"
            invalid={!!errors.confirm}
            {...register("confirm")}
          />
        </Field>

        <div className="flex items-center justify-end pt-2">
          <Button
            type="submit"
            variant="primary"
            uppercase
            loading={isSubmitting || mutation.isPending}
            leadingIcon={<Icon icon={KeyRound} size={14} />}
          >
            change password
          </Button>
        </div>
      </form>
    </Panel>
  );
}

function Field({
  id,
  label,
  error,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className="block font-mono text-[10px] uppercase tracking-[0.06em] text-ink-muted mb-1.5"
      >
        {label}
      </label>
      {children}
      {error && (
        <div
          role="alert"
          className="mt-1 font-mono text-[10px] uppercase tracking-[0.04em] text-err"
        >
          {error}
        </div>
      )}
    </div>
  );
}

