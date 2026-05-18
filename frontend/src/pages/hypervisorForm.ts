import { z } from "zod";
import { HYPERVISOR_TYPES } from "@/api/hypervisors";

// Port field rule, shared between the create and edit forms — an empty
// string means "no explicit port" (e.g. VMware Workstation), otherwise it
// must be a valid 1–65535 integer.
const portField = z
  .string()
  .max(5, "Port must be between 1 and 65535")
  .refine(
    (v) => v === "" || (/^\d+$/.test(v) && +v >= 1 && +v <= 65535),
    "Port must be between 1 and 65535",
  );

export const hypervisorCreateSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(1000).optional().or(z.literal("")),
  type: z.enum(HYPERVISOR_TYPES),
  host: z.string().min(1, "Host is required").max(255),
  port: portField,
  username: z.string().min(1, "Username is required").max(255),
  password: z.string().min(1, "Password is required"),
  verify_ssl: z.boolean(),
});

export type HypervisorCreateValues = z.infer<typeof hypervisorCreateSchema>;

/**
 * Edit-form schema — same constraints as create, with two differences:
 *  - `type` is omitted (the hypervisor type cannot be changed after creation).
 *  - `password` is optional: blank means "keep the current credential".
 * Shared so the edit drawer gets the same inline Zod validation the create
 * drawer has, instead of unvalidated raw `useState` fields (F9).
 */
export const hypervisorEditSchema = z.object({
  name: z.string().min(1, "Name is required").max(255),
  description: z.string().max(1000).optional().or(z.literal("")),
  host: z.string().min(1, "Host is required").max(255),
  port: portField,
  username: z.string().min(1, "Username is required").max(255),
  // Blank = unchanged. When supplied it carries no min-length rule because
  // the backend stores the credential opaquely and never re-validates it.
  password: z.string().max(255),
  verify_ssl: z.boolean(),
  is_active: z.boolean(),
});

export type HypervisorEditValues = z.infer<typeof hypervisorEditSchema>;

/** Parse a port input string to a number, or `null` when the field is blank. */
export function portToNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  return Number(trimmed);
}
