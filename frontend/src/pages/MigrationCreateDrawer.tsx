import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { AxiosError } from "axios";
import { ArrowRight, Search } from "lucide-react";
import toast from "react-hot-toast";
import { z } from "zod";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Skeleton } from "@/components/ui/Skeleton";
import { SlideOver } from "@/components/ui/SlideOver";
import { Textarea } from "@/components/ui/Textarea";
import {
  MIGRATION_STRATEGIES,
  createMigration,
  startMigration,
  type MigrationStrategy,
} from "@/api/migrations";
import { listVms, type Vm } from "@/api/vms";
import { useHasPermission } from "@/lib/permissions";
import type { ApiError } from "@/api/types";

const STRATEGY_HINT: Record<MigrationStrategy, string> = {
  auto: "let the platform pick — recommended.",
  direct: "no format conversion. Source must already be qcow2 / raw.",
  conversion: "force VMDK/VHD → QCOW2 via qemu-img.",
  hybrid: "mix direct + conversion across disks.",
  cold: "VM is shut down for the entire transfer.",
  warm: "transfer with online replication, then cutover.",
};

const schema = z.object({
  vm_id: z.string().min(1, "select a vm"),
  strategy: z.enum(MIGRATION_STRATEGIES),
  target_storage_class: z.string().min(1, "required").max(255),
  notes: z.string().max(2000).optional().or(z.literal("")),
  start_now: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

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

  // Server-side filtered VM picker. We cap at 200 because the picker is a
  // search-as-you-type — anything broader should be done from the VMs page.
  const vmsQuery = useQuery({
    queryKey: ["vms", "picker", vmSearch],
    queryFn: () => listVms({ skip: 0, limit: 200, ...(vmSearch.trim() ? { search: vmSearch.trim() } : {}) }),
    enabled: open,
    staleTime: 30_000,
  });

  const migratable = useMemo<Vm[]>(
    () => (vmsQuery.data?.items ?? []).filter((v) => v.can_migrate),
    [vmsQuery.data],
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
      strategy: "auto",
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

  const selectedStrategy = watch("strategy");

  const createMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const migration = await createMigration({
        vm_id: Number(values.vm_id),
        strategy: values.strategy,
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
          ? `migration #${m.id} created`
          : `migration #${m.id} started`,
      );
      queryClient.invalidateQueries({ queryKey: ["migrations"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "migrations"] });
      queryClient.invalidateQueries({ queryKey: ["vms"] });
      onClose();
    },
    onError: (err) => {
      toast.error(describeError(err, "creation failed"));
    },
  });

  const onSubmit: SubmitHandler<FormValues> = (values) => {
    createMutation.mutate(values);
  };

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title="new migration"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} type="button">
            cancel
          </Button>
          <Button
            type="submit"
            form="migration-create-form"
            variant="primary"
            uppercase
            loading={isSubmitting || createMutation.isPending}
            disabled={migratable.length === 0}
            trailingIcon={<Icon icon={ArrowRight} size={14} />}
          >
            create
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
        <Field label="search vm" id="m-search">
          <div className="relative">
            <Icon
              icon={Search}
              size={14}
              className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint pointer-events-none"
            />
            <Input
              id="m-search"
              placeholder="name, ip, hostname…"
              value={vmSearch}
              onChange={(e) => setVmSearch(e.target.value)}
              className="pl-8"
            />
          </div>
        </Field>

        <Field
          label="target vm"
          id="m-vm"
          error={errors.vm_id?.message}
          hint={
            !vmsQuery.isPending && migratable.length === 0
              ? "no migratable vm — a vm must be compatible/partial and not already migrating."
              : undefined
          }
        >
          {vmsQuery.isPending ? (
            <Skeleton className="h-9 w-full" />
          ) : (
            <Select id="m-vm" invalid={!!errors.vm_id} {...register("vm_id")}>
              <option value="">— select a vm —</option>
              {migratable.map((v) => (
                <option key={v.id} value={String(v.id)}>
                  {v.name} · {v.compatibility_status}
                </option>
              ))}
            </Select>
          )}
        </Field>

        <Field label="strategy" id="m-strategy" hint={STRATEGY_HINT[selectedStrategy]}>
          <Select id="m-strategy" {...register("strategy")}>
            {MIGRATION_STRATEGIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </Field>

        <Field
          label="storage class"
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

        <Field label="notes" id="m-notes" error={errors.notes?.message}>
          <Textarea id="m-notes" rows={3} {...register("notes")} />
        </Field>

        <div className="border-t border-line pt-4">
          <label className="flex items-start gap-3 cursor-pointer select-none">
            <input
              type="checkbox"
              className="mt-0.5 h-3.5 w-3.5 accent-signal"
              {...register("start_now")}
              disabled={!canStart}
            />
            <span className="flex flex-col gap-1">
              <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink">
                start immediately after create
              </span>
              <span className="font-mono text-[10px] text-ink-muted">
                {canStart
                  ? "enqueues the celery orchestrator straight away."
                  : "requires migrations:update — leaves the migration in PENDING."}
              </span>
            </span>
          </label>
        </div>

        <Callout tone="info" kicker="namespace">
          target namespace is fixed by your tenant —{" "}
          <span className="font-mono">shiftwise-&lt;tenant&gt;</span>. Cross-tenant
          migration is not permitted.
        </Callout>

        {migratable.length === 0 && !vmsQuery.isPending && (
          <Callout tone="warn">
            <div className="font-mono text-[11px]">
              <span className="kicker mr-2">no migratable vm</span>
              run discovery + analyzer on the hypervisors page first.
            </div>
          </Callout>
        )}

        <SelectedVmSummary
          id={watch("vm_id")}
          vms={migratable}
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

function SelectedVmSummary({ id, vms }: { id: string; vms: Vm[] }) {
  if (!id) return null;
  const vm = vms.find((v) => String(v.id) === id);
  if (!vm) return null;
  const rows: { label: string; value: string }[] = [
    { label: "os", value: vm.os_name ?? vm.os_type ?? "—" },
    { label: "cpu", value: `${vm.cpu_cores} vcpu` },
    { label: "ram", value: vm.memory_mb >= 1024 ? `${(vm.memory_mb / 1024).toFixed(1)} GB` : `${vm.memory_mb} MB` },
    { label: "disk", value: vm.disk_gb ? `${vm.disk_gb} GB` : "—" },
  ];
  return (
    <section className="border border-line bg-bg-elev p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="kicker">selected</span>
        <Badge variant={vm.compatibility_status === "compatible" ? "ok" : "partial"}>
          {vm.compatibility_status}
        </Badge>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between gap-2">
            <span className="kicker">{r.label}</span>
            <span className="font-mono text-[12px] tabular text-ink">{r.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
