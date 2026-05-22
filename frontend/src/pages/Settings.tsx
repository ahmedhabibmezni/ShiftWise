import { useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Ban, CheckCircle2, KeyRound, Save, UserCog } from "lucide-react";
import toast from "react-hot-toast";
import { z } from "zod";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Panel } from "@/components/ui/Panel";
import { PageHeader } from "@/components/ui/PageHeader";
import { RoleBadge } from "@/components/ui/RoleBadge";
import { changePassword } from "@/api/auth";
import { updateUser, type UpdateUserPayload } from "@/api/users";
import type { User } from "@/api/types";
import { describeError } from "@/lib/errors";
import { primaryRole } from "@/lib/permissions";
import { useAuthStore } from "@/store/auth";

const profileSchema = z.object({
  email: z.string().email("Invalid email address").max(255),
  username: z
    .string()
    .min(3, "Must be at least 3 characters")
    .max(100)
    .regex(
      /^[a-zA-Z][a-zA-Z0-9._-]*$/,
      "Must start with a letter (letters, digits, . _ - allowed)",
    ),
  first_name: z.string().max(100).optional().or(z.literal("")),
  last_name: z.string().max(100).optional().or(z.literal("")),
});
type ProfileValues = z.infer<typeof profileSchema>;

// Mirror of the backend UserUpdate.password validator. Replicating it here
// turns a 400 round-trip into an inline error.
const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Current password is required"),
    new_password: z
      .string()
      .min(8, "Must be at least 8 characters")
      .regex(/[A-Z]/, "Must contain an uppercase letter")
      .regex(/[a-z]/, "Must contain a lowercase letter")
      .regex(/\d/, "Must contain a digit")
      .regex(/[!@#$%^&*(),.?":{}|<>]/, "Must contain a special character"),
    confirm: z.string().min(1, "Confirm your new password"),
  })
  .refine((v) => v.new_password === v.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  })
  .refine((v) => v.current_password !== v.new_password, {
    message: "New password must differ from the current one",
    path: ["new_password"],
  });
type PasswordValues = z.infer<typeof passwordSchema>;

export default function Settings() {
  const user = useAuthStore((s) => s.user);

  if (!user) {
    return (
      <div>
        <Callout tone="err">Unable to load your account. Please log in again.</Callout>
      </div>
    );
  }

  return (
    <div className="max-w-[960px] mx-auto flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Your account, credentials, and session-scoped preferences."
      />

      <IdentityCard user={user} />
      <ProfileSection user={user} />
      <PasswordSection />
    </div>
  );
}

/* ------------------------------- identity --------------------------------- */

function IdentityCard({ user }: { user: User }) {
  const role = primaryRole(user) ?? "member";
  return (
    <Panel kicker="Signed in as" title={user.full_name || user.username}>
      <div className="flex items-center gap-3 flex-wrap mt-2">
        <RoleBadge role={role} />
        <StatusBadge
          icon={user.is_active ? CheckCircle2 : Ban}
          label={user.is_active ? "Active" : "Inactive"}
          tone={user.is_active ? "ok" : "muted"}
        />
        {user.is_verified && <StatusBadge icon={CheckCircle2} label="Verified" tone="info" />}
        <span className="text-[11px] uppercase tracking-[0.04em] font-bold text-[var(--text-secondary)]">
          Tenant · {user.tenant_id}
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
      toast.success("Profile saved");
      // Push the new user object into the auth store so the sidebar and
      // header pick it up without a hard refresh. /me is read once at boot
      // by AuthGate (no React Query), so there's nothing to invalidate —
      // the store is the authoritative source.
      setUser(next);
      queryClient.invalidateQueries({ queryKey: ["users"] });
      reset({
        email: next.email,
        username: next.username,
        first_name: next.first_name ?? "",
        last_name: next.last_name ?? "",
      });
    },
    onError: (err) => toast.error(describeError(err, "Save failed")),
  });

  const onSubmit: SubmitHandler<ProfileValues> = (values) => mutation.mutate(values);

  return (
    <Panel
      kicker="Profile"
      title="Account Details"
      action={<Icon icon={UserCog} size={16} className="text-[var(--text-muted)]" />}
    >
      <form
        id="settings-profile-form"
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="space-y-4 mt-2"
      >
        {mutation.isError && (
          <Callout tone="err" kicker="Save failed" role="alert">
            {describeError(
              mutation.error,
              "Could not save the profile. Please try again.",
            )}
          </Callout>
        )}

        <Field id="set-email" label="Email" error={errors.email?.message}>
          <Input
            id="set-email"
            type="email"
            autoComplete="email"
            invalid={!!errors.email}
            {...register("email")}
          />
        </Field>

        <Field id="set-username" label="Username" error={errors.username?.message}>
          <Input
            id="set-username"
            autoComplete="username"
            invalid={!!errors.username}
            {...register("username")}
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field id="set-first" label="First Name" error={errors.first_name?.message}>
            <Input
              id="set-first"
              autoComplete="given-name"
              invalid={!!errors.first_name}
              {...register("first_name")}
            />
          </Field>
          <Field id="set-last" label="Last Name" error={errors.last_name?.message}>
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
            loading={isSubmitting || mutation.isPending}
            disabled={!isDirty}
            leadingIcon={<Icon icon={Save} size={14} />}
          >
            Save Profile
          </Button>
        </div>
      </form>
    </Panel>
  );
}

/* ------------------------------- password --------------------------------- */

function PasswordSection() {
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
      // Audit H-06: a self password change goes through /auth/change-password,
      // which verifies the current password server-side.
      changePassword({
        current_password: values.current_password,
        new_password: values.new_password,
      }),
    onSuccess: () => {
      toast.success("Password updated · keep it safe");
      reset();
    },
    onError: (err) => toast.error(describeError(err, "Password update failed")),
  });

  const onSubmit: SubmitHandler<PasswordValues> = (values) => mutation.mutate(values);

  return (
    <Panel
      kicker="Security"
      title="Change Password"
      action={<Icon icon={KeyRound} size={16} className="text-[var(--text-muted)]" />}
    >
      <Callout tone="info" className="mt-2">
        Rotate periodically. Minimum 8 characters with uppercase, lowercase, digit, and special character.
      </Callout>

      <form
        id="settings-password-form"
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="space-y-4 mt-4"
      >
        {mutation.isError && (
          <Callout tone="err" kicker="Password change failed" role="alert">
            {describeError(
              mutation.error,
              "Could not update the password. Verify the current password and the new-password requirements.",
            )}
          </Callout>
        )}

        <Field
          id="set-current"
          label="Current Password"
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
          label="New Password"
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

        <Field id="set-confirm" label="Confirm" error={errors.confirm?.message}>
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
            loading={isSubmitting || mutation.isPending}
            leadingIcon={<Icon icon={KeyRound} size={14} />}
          >
            Change Password
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
        className="block text-[12px] font-bold uppercase tracking-[0.04em] text-[var(--text-secondary)] mb-1.5"
      >
        {label}
      </label>
      {children}
      {error && (
        <div
          role="alert"
          className="mt-1.5 text-[12px] text-[var(--alert-critical)]"
        >
          {error}
        </div>
      )}
    </div>
  );
}

