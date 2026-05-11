import { useEffect, useState } from "react";
import { useForm, type SubmitHandler } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { Check, Plug, X } from "lucide-react";
import toast from "react-hot-toast";
import { z } from "zod";
import { Button } from "@/components/ui/Button";
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
  vmware_workstation: "absolute path to vmrun.exe",
  kvm: "qemu+ssh://user@host/system",
  hyper_v: "Windows hostname (WinRM)",
  proxmox: "https://host (8006 default)",
  ovirt: "https://manager.example.com/ovirt-engine/api",
};

const createSchema = z.object({
  name: z.string().min(1, "name required").max(255),
  description: z.string().max(1000).optional().or(z.literal("")),
  type: z.enum(HYPERVISOR_TYPES),
  host: z.string().min(1, "host required").max(255),
  port: z
    .string()
    .max(5, "invalid port")
    .refine(
      (v) => v === "" || (/^\d+$/.test(v) && +v >= 1 && +v <= 65535),
      "invalid port",
    ),
  username: z.string().min(1, "username required").max(255),
  password: z.string().min(1, "password required"),
  verify_ssl: z.boolean(),
});

function portToNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return Number(trimmed);
}

type CreateFormValues = z.infer<typeof createSchema>;

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
    reset,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<CreateFormValues>({
    resolver: zodResolver(createSchema),
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

  useEffect(() => {
    if (!open) {
      reset();
      setTestResult(null);
    }
  }, [open, reset]);

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
        message: extractDetail(err, "test failed"),
        vms_count: null,
        error: extractDetail(err, "network error"),
      });
    },
  });

  const createMutation = useMutation({
    mutationFn: (values: CreateFormValues) =>
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
      toast.success(`hypervisor ${created.name} created`);
      queryClient.invalidateQueries({ queryKey: ["hypervisors"] });
      queryClient.invalidateQueries({ queryKey: ["stats", "hypervisors"] });
      onClose();
    },
    onError: (err) => {
      toast.error(extractDetail(err, "creation failed"));
    },
  });

  const onSubmit: SubmitHandler<CreateFormValues> = (values) => {
    createMutation.mutate(values);
  };

  const canSubmit =
    !createMutation.isPending && !testMutation.isPending;

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      title="new hypervisor"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} type="button">
            cancel
          </Button>
          <Button
            type="submit"
            form="hypervisor-create-form"
            variant="primary"
            loading={isSubmitting || createMutation.isPending}
            disabled={!canSubmit}
          >
            create
          </Button>
        </>
      }
    >
      <form
        id="hypervisor-create-form"
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="space-y-5"
      >
        <Field label="name" id="hv-name" error={errors.name?.message}>
          <Input
            id="hv-name"
            autoFocus
            invalid={!!errors.name}
            {...register("name")}
          />
        </Field>

        <Field label="type" id="hv-type" error={errors.type?.message}>
          <Select id="hv-type" invalid={!!errors.type} {...register("type")}>
            {HYPERVISOR_TYPES.map((t) => (
              <option key={t} value={t}>
                {t.replace(/_/g, " ")}
              </option>
            ))}
          </Select>
        </Field>

        <Field
          label="host"
          id="hv-host"
          error={errors.host?.message}
          hint={HOST_HINT[selectedType]}
        >
          <Input id="hv-host" invalid={!!errors.host} {...register("host")} />
        </Field>

        <Field label="port" id="hv-port" error={errors.port?.message}>
          <Input
            id="hv-port"
            type="number"
            inputMode="numeric"
            invalid={!!errors.port}
            {...register("port")}
          />
        </Field>

        <Field label="username" id="hv-username" error={errors.username?.message}>
          <Input
            id="hv-username"
            autoComplete="username"
            invalid={!!errors.username}
            {...register("username")}
          />
        </Field>

        <Field label="password" id="hv-password" error={errors.password?.message}>
          <Input
            id="hv-password"
            type="password"
            autoComplete="new-password"
            invalid={!!errors.password}
            {...register("password")}
          />
        </Field>

        <label className="flex items-center gap-2 cursor-pointer">
          <Checkbox {...register("verify_ssl")} />
          <span className="font-mono text-[11px] uppercase tracking-[0.05em] text-ink">
            verify ssl certificate
          </span>
        </label>

        <Field
          label="description"
          id="hv-description"
          error={errors.description?.message}
        >
          <Textarea
            id="hv-description"
            rows={2}
            {...register("description")}
          />
        </Field>

        <div className="pt-4 border-t border-line space-y-3">
          <Button
            type="button"
            variant="secondary"
            onClick={() => testMutation.mutate()}
            loading={testMutation.isPending}
            leadingIcon={<Icon icon={Plug} size={16} />}
            className="w-full"
          >
            test connection
          </Button>
          {testResult && <TestResultBanner result={testResult} />}
        </div>
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

function TestResultBanner({ result }: { result: TestConnectionResult }) {
  const tone = result.success ? "ok" : "err";
  const color = tone === "ok" ? "var(--ok)" : "var(--err)";
  return (
    <div
      role="status"
      className="border bg-bg-elev-2 p-3 space-y-1"
      style={{ borderColor: color }}
    >
      <div className="flex items-center gap-2" style={{ color }}>
        <Icon icon={result.success ? Check : X} size={16} />
        <span className="font-mono text-[11px] uppercase tracking-[0.05em]">
          {result.message}
        </span>
      </div>
      {result.success && result.vms_count !== null && (
        <div className="font-mono text-[10px] text-ink-muted pl-6">
          {result.vms_count} vms detected
        </div>
      )}
      {!result.success && result.error && (
        <div className="font-mono text-[10px] text-ink-muted pl-6 break-all">
          {result.error}
        </div>
      )}
    </div>
  );
}
