import { z } from "zod";

// Mirrors the backend UserCreate password validator. Keeping the messages
// in sync avoids the user seeing a generic 422 from FastAPI when a rule
// fails — we surface the same constraint locally.
const passwordRules = z
  .string()
  .min(8, "Must be at least 8 characters")
  .regex(/[A-Z]/, "Must contain an uppercase letter")
  .regex(/[a-z]/, "Must contain a lowercase letter")
  .regex(/\d/, "Must contain a digit")
  .regex(/[!@#$%^&*(),.?":{}|<>]/, "Must contain a special character");

// Username rule, shared between the create and edit forms.
const usernameField = z
  .string()
  .min(3, "Must be at least 3 characters")
  .max(100)
  .regex(
    /^[a-zA-Z][a-zA-Z0-9._-]*$/,
    "Must start with a letter (letters, digits, . _ - allowed)",
  );

export const userCreateSchema = z.object({
  email: z.string().min(1, "Email is required").email("Invalid email address"),
  username: usernameField,
  first_name: z.string().max(100).optional().or(z.literal("")),
  last_name: z.string().max(100).optional().or(z.literal("")),
  tenant_id: z
    .string()
    .min(1, "Tenant is required")
    .max(100)
    .regex(/^[a-z0-9-]+$/, "Lowercase letters, digits, and hyphens only"),
  is_active: z.boolean(),
  password: passwordRules,
  role_id: z.string().min(1, "Role is required"),
});

export type UserCreateValues = z.infer<typeof userCreateSchema>;

/**
 * Edit-form schema — same field constraints as create, with two differences:
 *  - `tenant_id` is omitted (a user's tenant is immutable; `UpdateUserPayload`
 *    has no `tenant_id` field).
 *  - `password` is optional: blank means "keep the current credential". When
 *    supplied it must still satisfy the full strength rules.
 * Shared so the edit drawer gets the same inline Zod validation as create,
 * instead of unvalidated raw `useState` fields (F9).
 */
export const userEditSchema = z.object({
  email: z.string().min(1, "Email is required").email("Invalid email address"),
  username: usernameField,
  first_name: z.string().max(100).optional().or(z.literal("")),
  last_name: z.string().max(100).optional().or(z.literal("")),
  is_active: z.boolean(),
  // Blank = unchanged. A non-blank value is held to the same rules as create.
  password: z.literal("").or(passwordRules),
  role_ids: z.array(z.number()),
});

export type UserEditValues = z.infer<typeof userEditSchema>;
