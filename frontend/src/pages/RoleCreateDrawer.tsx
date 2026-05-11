import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { AxiosError } from "axios";
import toast from "react-hot-toast";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Input } from "@/components/ui/Input";
import { PermissionsMatrix } from "@/components/ui/PermissionsMatrix";
import { Skeleton } from "@/components/ui/Skeleton";
import { SlideOver } from "@/components/ui/SlideOver";
import { Textarea } from "@/components/ui/Textarea";
import { createRole, getRoleResources, type RolePermissions } from "@/api/roles";
import type { ApiError } from "@/api/types";

// Mirror of backend RoleBase.validate_name. Tight slug rule prevents the API
// from rejecting our payload — we'd rather show inline errors than round-trip
// to a 400.
const schema = z.object({
  name: z
    .string()
    .min(2, "min 2 characters")
    .max(50, "max 50 characters")
    .regex(/^[a-z0-9_]+$/i, "letters, digits, underscores only"),
  description: z.string().max(500).optional().or(z.literal("")),
  is_active: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

function describeError(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    if (data?.detail) return data.detail;
  }
  return fallback;
}

function countGrants(perms: RolePermissions): number {
  return Object.values(perms).reduce(
    (acc, v) => acc + (v.includes("*") ? 4 : v.length),
    0,
  );
}

export function RoleCreateDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [permissions, setPermissions] = useState<RolePermissions>({});

  const resourcesQuery = useQuery({
    queryKey: ["roles", "resources"],
    queryFn: getRoleResources,
    enabled: open,
    staleTime: 60 * 60_000,
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", description: "", is_active: true },
  });

  useEffect(() => {
    if (!open) {
      reset();
      setPermissions({});
    }
  }, [open, reset]);

  const createMutation = useMutation({
    mutationFn: (values: FormValues) =>
      createRole({
        name: values.name.toLowerCase(),
        description: values.description || null,
        permissions,
        is_active: values.is_active,
      }),
    onSuccess: (role) => {
      toast.success(`role ${role.name} created`);
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      onClose();
    },
    onError: (err) => toast.error(describeError(err, "creation failed")),
  });

  const onSubmit: SubmitHandler<FormValues> = (values) => {
    createMutation.mutate(values);
  };

  const grants = countGrants(permissions);

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title="new role"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} type="button">
            cancel
          </Button>
          <Button
            type="submit"
            form="role-create-form"
            variant="primary"
            uppercase
            loading={isSubmitting || createMutation.isPending}
            disabled={grants === 0}
            title={grants === 0 ? "grant at least one permission first" : undefined}
          >
            create
          </Button>
        </>
      }
    >
      <form
        id="role-create-form"
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="space-y-5"
      >
        <Field id="role-name" label="name" error={errors.name?.message} hint="lowercase slug · letters, digits, underscores">
          <Input
            id="role-name"
            autoFocus
            invalid={!!errors.name}
            {...register("name")}
          />
        </Field>

        <Field id="role-description" label="description" error={errors.description?.message}>
          <Textarea id="role-description" rows={2} {...register("description")} />
        </Field>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            className="h-3.5 w-3.5 accent-signal"
            {...register("is_active")}
          />
          <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink">
            active
          </span>
        </label>

        <section>
          <div className="kicker mb-2">permissions matrix</div>
          {resourcesQuery.data ? (
            <PermissionsMatrix
              resources={resourcesQuery.data.resources}
              permissions={permissions}
              onChange={setPermissions}
              describeResource={(r) => resourcesQuery.data.description[r]}
            />
          ) : (
            <Skeleton className="h-48 w-full" />
          )}
          <div className="mt-2 font-mono text-[10px] uppercase tracking-[0.06em] text-ink-muted">
            {grants === 0
              ? "no grants yet — pick at least one action."
              : `${grants} grant${grants > 1 ? "s" : ""} configured`}
          </div>
        </section>

        <Callout tone="info">
          system roles cannot be created from the UI — only the four seeded at
          install (super_admin, admin, user, viewer) carry that flag.
        </Callout>
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
