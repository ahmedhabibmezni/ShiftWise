import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { AxiosError } from "axios";
import { ArrowRight, Search } from "lucide-react";
import { Checkbox } from "@/components/ui/Checkbox";
import toast from "react-hot-toast";
import { z } from "zod";
import { CompatibilityBadge, type CompatibilityKey } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { SlideOver } from "@/components/ui/SlideOver";
import { Textarea } from "@/components/ui/Textarea";
import { createMigration, startMigration } from "@/api/migrations";
import { listVms, type Vm } from "@/api/vms";
import { useHasPermission } from "@/lib/permissions";
import type { ApiError } from "@/api/types";

const schema = z.object({
  vm_id: z.string().min(1, "Select a VM"),
  target_storage_class: z.string().min(1, "Storage class is required").max(255),
  notes: z.string().max(2000).optional().or(z.literal("")),
  start_now: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

// A VM is migratable only once the analyzer has graded it compatible or
// partial and it is not already in flight (VirtualMachine.can_migrate on
// the backend). Non-migratable VMs still appear in the picker — disabled,
// with the reason inline — so the operator sees their VMs instead of an
// empty dropdown.
function migrationBlockReason(vm: Vm): string | null {
  if (vm.can_migrate) return null;
  if (vm.compatibility_status === "unknown") return "not analyzed";
  if (vm.compatibility_status === "incompatible") return "incompatible";
  if (vm.status === "migrating") return "migrating";
  if (vm.status === "migrated") return "already migrated";
  if (vm.status === "archived") return "archived";
  if (vm.status === "analyzing") return "analyzing";
  return vm.status;
}

function describeError(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    if (data?.detail) return data.detail;
  }
  return fallback;
}

export function MigrationCreateDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const canStart = useHasPermission("migrations", "update");
  const [vmSearch, setVmSearch] = useState("");

  // Server-side filtered VM picker. Capped at 100 (backend max le=100).
  // For broader scans, use the VMs page.
  const vmsQuery = useQuery({
    queryKey: ["vms", "picker", vmSearch],
    queryFn: () => listVms({ skip: 0, limit: 100, ...(vmSearch.trim() ? { search: vmSearch.trim() } : {}) }),
    enabled: open,
    staleTime: 30_000,
  });

  const allVms = useMemo<Vm[]>(
    () => vmsQuery.data?.items ?? [],
    [vmsQuery.data],
  );
  const migratable = useMemo<Vm[]>(
    () => allVms.filter((v) => v.can_migrate),
    [allVms],
  );

  const {
    register,
    handleSubmit,
    watch,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      vm_id: "",
      target_storage_class: "nfs-client",
      notes: "",
      start_now: true,
    },
  });

  useEffect(() => {
    if (!open) {
      reset();
      setVmSearch("");
    }
  }, [open, reset]);

  const createMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const migration = await createMigration({
        vm_id: Number(values.vm_id),
        // Strategy is always AUTO — the compatibility analyzer selects the
        // concrete strategy. The form no longer exposes a manual override.
        strategy: "auto",
        target_storage_class: values.target_storage_class,
        notes: values.notes || null,
      });
      // The "start" toggle is a deliberate UX shortcut: most operators want
      // to create + launch in one click. If the post-create start fails the
      // migration still exists in PENDING and the operator can retry from
      // the detail drawer.
      if (values.start_now && canStart) {
        try {
          return await startMigration(migration.id);
        } catch (err) {
          toast.error(describeError(err, "created but failed to start"));
          return migration;
        }
      }
      return migration;
    },
    onSuccess: (m) => {
      toast.success(
        m.status === "pending"
          ? `Migration #${m.id} created`
          : `Migration #${m.id} started`,
      );
      queryClient.invalidateQueries({ queryKey: ["migrations"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "migrations"] });
      queryClient.invalidateQueries({ queryKey: ["vms"] });
      onClose();
    },
    onError: (err) => {
      toast.error(describeError(err, "Creation failed"));
    },
  });

  const onSubmit: SubmitHandler<FormValues> = (values) => {
    createMutation.mutate(values);
  };

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title="New Migration"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button
            type="submit"
            form="migration-create-form"
            variant="primary"
            loading={isSubmitting || createMutation.isPending}
            disabled={migratable.length === 0}
            trailingIcon={<Icon icon={ArrowRight} size={14} />}
          >
            Create
          </Button>
        </>
      }
    >
      <form
        id="migration-create-form"
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="space-y-5"
      >
        <Field label="Search VM" id="m-search">
          <div className="relative">
            <Icon
              icon={Search}
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none"
            />
            <Input
              id="m-search"
              placeholder="Name, IP, hostname…"
              value={vmSearch}
              onChange={(e) => setVmSearch(e.target.value)}
              className="pl-9"
            />
          </div>
        </Field>

        <Field
          label="Target VM"
          id="m-vm"
          error={errors.vm_id?.message}
          hint={
            !vmsQuery.isPending && allVms.length > 0 && migratable.length === 0
              ? "Greyed-out VMs aren't ready — analyze them on the VMs page first."
              : undefined
          }
        >
          {vmsQuery.isPending ? (
            <Skeleton className="h-10 w-full" />
          ) : (
            <Select id="m-vm" invalid={!!errors.vm_id} {...register("vm_id")}>
              <option value="">Select a VM</option>
              {allVms.map((v) => {
                const reason = migrationBlockReason(v);
                return (
                  <option
                    key={v.id}
                    value={String(v.id)}
                    disabled={reason !== null}
                  >
                    {v.name} · {reason ?? v.compatibility_status}
                  </option>
                );
              })}
            </Select>
          )}
        </Field>

        <Field
          label="Strategy"
          id="m-strategy"
          hint="The compatibility analyzer selects the optimal strategy automatically."
        >
          <Select id="m-strategy" defaultValue="auto" disabled>
            <option value="auto">Auto — decided by the analyzer</option>
          </Select>
        </Field>

        <Field
          label="Storage Class"
          id="m-storage"
          error={errors.target_storage_class?.message}
          hint="OpenShift StorageClass for the destination PVC. Default: nfs-client."
        >
          <Input
            id="m-storage"
            invalid={!!errors.target_storage_class}
            {...register("target_storage_class")}
          />
        </Field>

        <Field label="Notes" id="m-notes" error={errors.notes?.message}>
          <Textarea id="m-notes" rows={3} {...register("notes")} />
        </Field>

        <div className="border-t border-[var(--hairline)] pt-4">
          <label className="flex items-start gap-3 cursor-pointer select-none">
            <Checkbox
              className="mt-0.5"
              {...register("start_now")}
              disabled={!canStart}
            />
            <span className="flex flex-col gap-1">
              <span className="text-[13px] font-bold text-[var(--text-primary)]">
                Start immediately after create
              </span>
              <span className="text-[12px] text-[var(--text-secondary)]">
                {canStart
                  ? "Enqueues the Celery orchestrator straight away."
                  : "Requires migrations:update — leaves the migration in PENDING."}
              </span>
            </span>
          </label>
        </div>

        <Callout tone="info" kicker="Namespace">
          Target namespace is fixed by your tenant —{" "}
          <span className="font-bold">shiftwise-&lt;tenant&gt;</span>. Cross-tenant
          migration is not permitted.
        </Callout>

        {!vmsQuery.isPending && allVms.length === 0 && (
          <Callout tone="warn" kicker="No VMs">
            No VMs were discovered for your tenant. Run discovery on the
            Hypervisors page first.
          </Callout>
        )}

        {!vmsQuery.isPending && allVms.length > 0 && migratable.length === 0 && (
          <Callout tone="warn" kicker="Nothing Migratable">
            None of your VMs are ready to migrate. Analyze them on the VMs
            page to determine compatibility first.
          </Callout>
        )}

        <SelectedVmSummary
          id={watch("vm_id")}
          vms={allVms}
        />
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

function SelectedVmSummary({ id, vms }: { id: string; vms: Vm[] }) {
  if (!id) return null;
  const vm = vms.find((v) => String(v.id) === id);
  if (!vm) return null;
  const rows: { label: string; value: string }[] = [
    { label: "OS", value: vm.os_name ?? vm.os_type ?? "—" },
    { label: "CPU", value: `${vm.cpu_cores} vCPU` },
    { label: "RAM", value: vm.memory_mb >= 1024 ? `${(vm.memory_mb / 1024).toFixed(1)} GB` : `${vm.memory_mb} MB` },
    { label: "Disk", value: vm.disk_gb ? `${vm.disk_gb} GB` : "—" },
  ];
  return (
    <section className="rounded-2xl bg-[var(--surface-soft)] p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="kicker">Selected</span>
        <CompatibilityBadge status={vm.compatibility_status.toUpperCase() as CompatibilityKey} />
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between gap-2">
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">{r.label}</span>
            <span className="text-[13px] font-bold tabular text-[var(--text-primary)]">{r.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
