import { useEffect, useState } from "react";
import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Check, Plug, X } from "lucide-react";
import toast from "react-hot-toast";
import { Button } from "@/components/ui/Button";
import { Callout } from "@/components/ui/Callout";
import { Checkbox } from "@/components/ui/Checkbox";
import { Icon } from "@/components/ui/Icon";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { SlideOver } from "@/components/ui/SlideOver";
import { Textarea } from "@/components/ui/Textarea";
import {
  HYPERVISOR_TYPES,
  createHypervisor,
  testHypervisorConnection,
  type HypervisorType,
  type TestConnectionResult,
} from "@/api/hypervisors";
import type { ApiError } from "@/api/types";
import {
  hypervisorCreateSchema,
  portToNumber,
  type HypervisorCreateValues,
} from "./hypervisorForm";

const DEFAULT_PORT: Record<HypervisorType, string> = {
  vsphere: "443",
  vmware_esxi: "443",
  vmware_workstation: "",
  hyper_v: "5985",
  kvm: "22",
  proxmox: "8006",
  ovirt: "443",
  virtualbox: "",
  xen: "443",
  other: "",
};

const HOST_HINT: Partial<Record<HypervisorType, string>> = {
  vsphere: "e.g. vcenter.example.com",
  vmware_esxi: "e.g. esxi-01.example.com",
  vmware_workstation: "e.g. C:\\Program Files\\VMware\\vmrun.exe",
  hyper_v: "e.g. dc-west-02 (WinRM hostname)",
  kvm: "e.g. qemu+ssh://user@host/system",
  proxmox: "e.g. https://pve.example.com",
  ovirt: "e.g. https://manager.example.com/ovirt-engine/api",
};

function extractDetail(err: unknown, fallback: string): string {
  if (err instanceof AxiosError) {
    const data = err.response?.data as ApiError | undefined;
    if (data?.detail) return data.detail;
  }
  return fallback;
}

export function HypervisorCreateDrawer({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<HypervisorCreateValues>({
    resolver: zodResolver(hypervisorCreateSchema),
    defaultValues: {
      name: "",
      description: "",
      type: "kvm",
      host: "",
      port: DEFAULT_PORT.kvm,
      username: "",
      password: "",
      verify_ssl: false,
    },
  });

  const selectedType = watch("type");

  // No reset-on-close effect: the parent remounts this drawer via a `key`
  // on every open, so the form and test-connection result start blank.

  useEffect(() => {
    setValue("port", DEFAULT_PORT[selectedType]);
    setTestResult(null);
  }, [selectedType, setValue]);

  const testMutation = useMutation({
    mutationFn: () => {
      const v = watch();
      return testHypervisorConnection({
        type: v.type,
        host: v.host,
        port: portToNumber(v.port),
        username: v.username,
        password: v.password,
        verify_ssl: v.verify_ssl,
      });
    },
    onSuccess: (data) => setTestResult(data),
    onError: (err) => {
      setTestResult({
        success: false,
        message: extractDetail(err, "Connection test failed"),
        vms_count: null,
        error: extractDetail(err, "Network error. Check the host and port."),
      });
    },
  });

  const createMutation = useMutation({
    mutationFn: (values: HypervisorCreateValues) =>
      createHypervisor({
        name: values.name,
        description: values.description || null,
        type: values.type,
        host: values.host,
        port: portToNumber(values.port),
        username: values.username,
        password: values.password,
        verify_ssl: values.verify_ssl,
      }),
    onSuccess: (created) => {
      toast.success(`Hypervisor ${created.name} created`);
      queryClient.invalidateQueries({ queryKey: ["hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "hypervisors"] });
      onClose();
    },
    onError: (err) => {
      toast.error(extractDetail(err, "Creation failed"));
    },
  });

  const onSubmit: SubmitHandler<HypervisorCreateValues> = (values) => {
    createMutation.mutate(values);
  };

  const canSubmit =
    !createMutation.isPending && !testMutation.isPending;

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title="New Hypervisor"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} type="button">
            Cancel
          </Button>
          <Button
            type="submit"
            form="hypervisor-create-form"
            variant="primary"
            loading={isSubmitting || createMutation.isPending}
            disabled={!canSubmit}
          >
            Create
          </Button>
        </>
      }
    >
      <form
        id="hypervisor-create-form"
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="space-y-7"
      >
        {/* Persistent inline error — a failed create otherwise surfaces
            only as an auto-dismissing toast, easy to miss (F12). */}
        {createMutation.isError && (
          <Callout tone="err" kicker="Creation failed" role="alert">
            {extractDetail(
              createMutation.error,
              "Could not create the hypervisor. Check the fields and try again.",
            )}
          </Callout>
        )}

        <Fieldset legend="Identity">
          <Field label="Name" id="hv-name" error={errors.name?.message}>
            <Input
              id="hv-name"
              autoFocus
              invalid={!!errors.name}
              {...register("name")}
            />
          </Field>

          <Field label="Type" id="hv-type" error={errors.type?.message}>
            <Select id="hv-type" invalid={!!errors.type} {...register("type")}>
              {HYPERVISOR_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                </option>
              ))}
            </Select>
          </Field>

          <Field
            label="Description"
            id="hv-description"
            error={errors.description?.message}
          >
            <Textarea id="hv-description" rows={2} {...register("description")} />
          </Field>
        </Fieldset>

        <Fieldset legend="Connection">
          <div className="grid grid-cols-1 sm:grid-cols-[1fr_104px] gap-3 items-start">
            <Field
              label="Host"
              id="hv-host"
              error={errors.host?.message}
              hint={HOST_HINT[selectedType]}
            >
              <Input id="hv-host" invalid={!!errors.host} {...register("host")} />
            </Field>

            <Field label="Port" id="hv-port" error={errors.port?.message}>
              <Input
                id="hv-port"
                type="number"
                inputMode="numeric"
                invalid={!!errors.port}
                {...register("port")}
              />
            </Field>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 items-start">
            <Field
              label="Username"
              id="hv-username"
              error={errors.username?.message}
            >
              <Input
                id="hv-username"
                autoComplete="username"
                invalid={!!errors.username}
                {...register("username")}
              />
            </Field>

            <Field
              label="Password"
              id="hv-password"
              error={errors.password?.message}
            >
              <Input
                id="hv-password"
                type="password"
                autoComplete="new-password"
                invalid={!!errors.password}
                {...register("password")}
              />
            </Field>
          </div>

          <label className="flex items-center gap-2.5 cursor-pointer">
            <Checkbox {...register("verify_ssl")} />
            <span className="text-[13px] text-[var(--text-primary)] font-medium">
              Verify SSL certificate
            </span>
          </label>

          <div className="space-y-3">
            <Button
              type="button"
              variant="secondary"
              onClick={() => testMutation.mutate()}
              loading={testMutation.isPending}
              leadingIcon={<Icon icon={Plug} size={16} />}
              className="w-full"
            >
              Test Connection
            </Button>
            {testResult && <TestResultBanner result={testResult} />}
          </div>
        </Fieldset>
      </form>
    </SlideOver>
  );
}

/** Labelled group of related fields. `<legend>` ties the heading to the
 *  controls for assistive tech; border reset keeps the glass aesthetic. */
function Fieldset({
  legend,
  children,
}: {
  legend: string;
  children: React.ReactNode;
}) {
  return (
    <fieldset className="m-0 min-w-0 border-0 p-0">
      <legend className="kicker mb-3.5">{legend}</legend>
      <div className="space-y-5">{children}</div>
    </fieldset>
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

function TestResultBanner({ result }: { result: TestConnectionResult }) {
  const success = result.success;
  return (
    <div
      role="status"
      className="rounded-xl p-3.5 space-y-1.5 border"
      style={{
        background: success ? "rgba(1, 181, 116, 0.08)" : "rgba(224, 61, 61, 0.08)",
        borderColor: success ? "rgba(1, 181, 116, 0.3)" : "rgba(224, 61, 61, 0.3)",
      }}
    >
      <div
        className="flex items-center gap-2"
        style={{
          color: success ? "var(--alert-success-light)" : "var(--alert-critical)",
        }}
      >
        <Icon icon={success ? Check : X} size={16} strokeWidth={2.25} />
        <span className="text-[12px] font-bold uppercase tracking-[0.04em]">
          {result.message}
        </span>
      </div>
      {result.success && result.vms_count !== null && (
        <div className="text-[12px] text-[var(--text-secondary)] pl-6">
          {result.vms_count} VMs detected
        </div>
      )}
      {!result.success && result.error && (
        <div className="text-[12px] text-[var(--text-secondary)] pl-6 break-all">
          {result.error}
        </div>
      )}
    </div>
  );
}
