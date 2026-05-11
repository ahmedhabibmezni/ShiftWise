import { useEffect } from "react";
import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import toast from "react-hot-toast";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { SlideOver } from "@/components/ui/SlideOver";
import { createUser, listRoles } from "@/api/users";
import { useAuthStore } from "@/store/auth";

// Mirrors the backend UserCreate password validator. Keeping the messages
// in sync avoids the user seeing a generic 422 from FastAPI when a rule
// fails — we surface the same constraint locally.
const passwordRules = z
  .string()
  .min(8, "min 8 characters")
  .regex(/[A-Z]/, "must contain an uppercase letter")
  .regex(/[a-z]/, "must contain a lowercase letter")
  .regex(/\d/, "must contain a digit")
  .regex(/[!@#$%^&*(),.?":{}|<>]/, "must contain a special character");

const createSchema = z.object({
  email: z.string().min(1, "email required").email("invalid email"),
  username: z
    .string()
    .min(3, "min 3 characters")
    .max(100)
    .regex(
      /^[a-zA-Z][a-zA-Z0-9._-]*$/,
      "letters, digits, . _ - only; must start with a letter",
    ),
  first_name: z.string().max(100).optional().or(z.literal("")),
  last_name: z.string().max(100).optional().or(z.literal("")),
  tenant_id: z
    .string()
    .min(1, "tenant required")
    .max(100)
    .regex(/^[a-z0-9-]+$/, "lowercase letters, digits and hyphens only"),
  is_active: z.boolean(),
  password: passwordRules,
  role_id: z.string().min(1, "role required"),
});

type CreateFormValues = z.infer<typeof createSchema>;

type FastApiValidationError = { msg?: string };

function extractDetail(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as
      | { detail?: string | FastApiValidationError[] }
      | undefined;
    const detail = data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (typeof first?.msg === "string") return first.msg;
    }
  }
  return fallback;
}

export function UserCreateDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const currentUser = useAuthStore((s) => s.user);

  const rolesQuery = useQuery({
    queryKey: ["roles"],
    queryFn: listRoles,
    staleTime: 5 * 60_000,
    enabled: open,
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<CreateFormValues>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      email: "",
      username: "",
      first_name: "",
      last_name: "",
      tenant_id: currentUser?.tenant_id ?? "",
      is_active: true,
      password: "",
      role_id: "",
    },
  });

  useEffect(() => {
    if (!open) reset();
  }, [open, reset]);

  const mutation = useMutation({
    mutationFn: (values: CreateFormValues) =>
      createUser({
        email: values.email,
        username: values.username,
        first_name: values.first_name || null,
        last_name: values.last_name || null,
        tenant_id: values.tenant_id,
        is_active: values.is_active,
        password: values.password,
        role_ids: [Number(values.role_id)],
      }),
    onSuccess: (created) => {
      toast.success(`User «${created.username}» created`);
      queryClient.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
    onError: (err) => {
      toast.error(extractDetail(err, "Failed to create user."));
    },
  });

  const onSubmit: SubmitHandler<CreateFormValues> = (values) => {
    mutation.mutate(values);
  };

  const roles = rolesQuery.data ?? [];

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title="new user"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} type="button">
            cancel
          </Button>
          <Button
            type="submit"
            form="user-create-form"
            variant="primary"
            loading={isSubmitting || mutation.isPending}
            disabled={mutation.isPending}
          >
            create
          </Button>
        </>
      }
    >
      <form
        id="user-create-form"
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="space-y-5"
      >
        <Field id="u-email" label="email" error={errors.email?.message}>
          <Input
            id="u-email"
            type="email"
            autoComplete="email"
            autoFocus
            invalid={!!errors.email}
            {...register("email")}
          />
        </Field>

        <Field id="u-username" label="username" error={errors.username?.message}>
          <Input
            id="u-username"
            autoComplete="off"
            invalid={!!errors.username}
            {...register("username")}
          />
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field
            id="u-first_name"
            label="first name"
            error={errors.first_name?.message}
          >
            <Input
              id="u-first_name"
              autoComplete="given-name"
              invalid={!!errors.first_name}
              {...register("first_name")}
            />
          </Field>
          <Field
            id="u-last_name"
            label="last name"
            error={errors.last_name?.message}
          >
            <Input
              id="u-last_name"
              autoComplete="family-name"
              invalid={!!errors.last_name}
              {...register("last_name")}
            />
          </Field>
        </div>

        <Field
          id="u-tenant_id"
          label="tenant"
          error={errors.tenant_id?.message}
          hint={
            currentUser
              ? `your tenant: ${currentUser.tenant_id}`
              : undefined
          }
        >
          <Input
            id="u-tenant_id"
            invalid={!!errors.tenant_id}
            {...register("tenant_id")}
          />
        </Field>

        <Field id="u-role_id" label="role" error={errors.role_id?.message}>
          <Select
            id="u-role_id"
            invalid={!!errors.role_id}
            disabled={rolesQuery.isPending}
            {...register("role_id")}
          >
            <option value="">
              {rolesQuery.isPending ? "loading…" : "select a role"}
            </option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
                {r.description ? ` — ${r.description}` : ""}
              </option>
            ))}
          </Select>
        </Field>

        <Field
          id="u-password"
          label="password"
          error={errors.password?.message}
          hint="≥ 8 chars · upper · lower · digit · special"
        >
          <Input
            id="u-password"
            type="password"
            autoComplete="new-password"
            invalid={!!errors.password}
            {...register("password")}
          />
        </Field>

        <label className="flex items-center gap-2 cursor-pointer">
          <Checkbox {...register("is_active")} />
          <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink">
            account active
          </span>
        </label>
      </form>
    </SlideOver>
  );
}

function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
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
      {hint && !error && (
        <div className="mt-1 font-mono text-[10px] text-ink-muted">{hint}</div>
      )}
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
