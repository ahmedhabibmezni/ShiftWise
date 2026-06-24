import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import toast from "react-hot-toast";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { PermissionsMatrix } from "@/components/ui/PermissionsMatrix";
import { Skeleton } from "@/components/ui/Skeleton";
import { SlideOver } from "@/components/ui/SlideOver";
import { Textarea } from "@/components/ui/Textarea";
import { createRole, getRoleResources, type RolePermissions } from "@/api/roles";
import { describeError } from "@/lib/errors";

// Mirror of backend RoleBase.validate_name. Tight slug rule prevents the API
// from rejecting our payload — we'd rather show inline errors than round-trip
// to a 400.
const schema = z.object({
  name: z
    .string()
    .min(2, "Must be at least 2 characters")
    .max(50, "Must be 50 characters or fewer")
    .regex(/^[a-z0-9_]+$/i, "Letters, digits, and underscores only"),
  description: z.string().max(500).optional().or(z.literal("")),
  is_active: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

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
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", description: "", is_active: true },
  });

  // No reset effect: the parent remounts this drawer via a `key` on every
  // open, so the form and permissions matrix start blank each time.

  const createMutation = useMutation({
    mutationFn: (values: FormValues) =>
      createRole({
        name: values.name.toLowerCase(),
        description: values.description || null,
        permissions,
        is_active: values.is_active,
      }),
    onSuccess: (role) => {
      toast.success(`Role ${role.name} created`);
      queryClient.invalidateQueries({ queryKey: ["roles"] });
      onClose();
    },
    onError: (err) => toast.error(describeError(err, "Creation failed")),
  });

  const onSubmit: SubmitHandler<FormValues> = (values) => {
    createMutation.mutate(values);
  };

  const grants = countGrants(permissions);

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title="New Role"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button
            type="submit"
            form="role-create-form"
            variant="primary"
            loading={isSubmitting || createMutation.isPending}
            disabled={grants === 0}
            title={grants === 0 ? "Grant at least one permission first" : undefined}
          >
            Create
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
        <Field id="role-name" label="Name" error={errors.name?.message} hint="Lowercase slug · letters, digits, underscores">
          <Input
            id="role-name"
            autoFocus
            invalid={!!errors.name}
            {...register("name")}
          />
        </Field>

        <Field id="role-description" label="Description" error={errors.description?.message}>
          <Textarea id="role-description" rows={2} {...register("description")} />
        </Field>

        <label className="flex items-center gap-2.5 cursor-pointer">
          <Checkbox {...register("is_active")} />
          <span className="text-[13px] text-[var(--text-primary)] font-medium">Active</span>
        </label>

        <section>
          <div className="kicker mb-2">Permissions Matrix</div>
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
          <div className="mt-2 text-[11px] text-[var(--text-muted)]">
            {grants === 0
              ? "No grants yet — pick at least one action."
              : `${grants} grant${grants > 1 ? "s" : ""} configured`}
          </div>
        </section>

        <Callout tone="info">
          System roles cannot be created from the UI — only the four seeded at
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
        className="block text-[12px] font-bold uppercase tracking-[0.04em] text-[var(--text-secondary)] mb-1.5"
      >
        {label}
      </label>
      {children}
      {hint && !error && (
        <div className="mt-1.5 text-[11px] text-[var(--text-muted)]">{hint}</div>
      )}
      {error && (
        <div role="alert" className="mt-1.5 text-[12px] text-[var(--alert-critical)]">
          {error}
        </div>
      )}
    </div>
  );
}
