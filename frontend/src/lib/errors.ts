import { AxiosError } from "axios";

/**
 * One FastAPI validation error item — the shape inside the `detail` array a
 * 422 response carries. Only `msg` is consumed; `loc`/`type` are ignored.
 */
type FastApiValidationError = { msg?: unknown };

/** Body shape of an error response: either `{detail: string}` or, for a 422,
 *  `{detail: ValidationError[]}`. */
type ErrorBody = {
  detail?: string | FastApiValidationError[];
};

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
  if (!(err instanceof AxiosError)) return fallback;

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

  return fallback;
}
