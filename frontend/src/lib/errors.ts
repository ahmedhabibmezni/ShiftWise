import { AxiosError } from "axios";

/**
 * One FastAPI validation error item — the shape inside the `detail` array a
 * 422 response carries. Only `msg` is consumed; `loc`/`type` are ignored.
 */
type FastApiValidationError = { msg?: unknown };

/** Structured error detail emitted by some routers (feature 002 infrastructure):
 *  `{ detail: { code, message } }`. Only `message` is surfaced to the user. */
type StructuredErrorDetail = { code?: unknown; message?: unknown };

/** Body shape of an error response: `{detail: string}`, a 422
 *  `{detail: ValidationError[]}`, or `{detail: {code, message}}`. */
type ErrorBody = {
  detail?: string | FastApiValidationError[] | StructuredErrorDetail;
};

/**
 * Extracts a human-readable message from the `detail` field of an error
 * response, handling the two shapes the backend emits:
 *
 * - `{ detail: "..." }` — every `HTTPException` raised by a route handler.
 * - `{ detail: [{ msg, loc, type }, ...] }` — FastAPI request-validation 422s.
 *
 * Returns `null` when `err` is not an Axios error or carries no usable
 * `detail` — callers that need to distinguish "no backend message" from a
 * fallback string use this directly; most callers go through `describeError`.
 */
export function describeErrorOrNull(err: unknown): string | null {
  if (!(err instanceof AxiosError)) return null;

  const detail = (err.response?.data as ErrorBody | undefined)?.detail;

  if (typeof detail === "string" && detail.length > 0) {
    return detail;
  }

  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (first && typeof first.msg === "string" && first.msg.length > 0) {
      return first.msg;
    }
  }

  // Structured `{code, message}` detail (feature 002 infrastructure router).
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const message = (detail as StructuredErrorDetail).message;
    if (typeof message === "string" && message.length > 0) {
      return message;
    }
  }

  return null;
}

/**
 * Single source of truth for turning an unknown thrown value into a
 * human-readable message. Handles the two shapes the backend emits:
 *
 * - `{ detail: "..." }` — every `HTTPException` raised by a route handler.
 * - `{ detail: [{ msg, loc, type }, ...] }` — FastAPI request-validation 422s.
 *
 * Anything else (network error, non-Axios throw, unexpected body) returns the
 * caller-supplied `fallback`. Previously this logic was copy-pasted into 10+
 * page modules; only the `UserCreateDrawer` copy handled the 422 array — so a
 * validation failure elsewhere surfaced a generic message.
 */
export function describeError(err: unknown, fallback: string): string {
  return describeErrorOrNull(err) ?? fallback;
}
