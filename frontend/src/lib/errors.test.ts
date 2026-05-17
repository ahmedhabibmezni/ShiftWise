import { describe, expect, it } from "vitest";
import { AxiosError } from "axios";
import { describeError } from "./errors";

function axiosErrorWith(data: unknown, status = 400): AxiosError {
  const err = new AxiosError("request failed");
  err.response = {
    data,
    status,
    statusText: "",
    headers: {},
    config: {} as never,
  };
  return err;
}

describe("describeError", () => {
  it("returns the fallback for a non-Axios error", () => {
    expect(describeError(new Error("boom"), "fallback")).toBe("fallback");
  });

  it("returns the fallback when there is no response body", () => {
    expect(describeError(new AxiosError("network"), "fallback")).toBe(
      "fallback",
    );
  });

  it("extracts a plain string `detail`", () => {
    const err = axiosErrorWith({ detail: "Hypervisor name already in use" });
    expect(describeError(err, "fallback")).toBe(
      "Hypervisor name already in use",
    );
  });

  it("extracts the first message from a FastAPI 422 detail array", () => {
    const err = axiosErrorWith(
      {
        detail: [
          { loc: ["body", "email"], msg: "value is not a valid email address" },
          { loc: ["body", "password"], msg: "field required" },
        ],
      },
      422,
    );
    expect(describeError(err, "fallback")).toBe(
      "value is not a valid email address",
    );
  });

  it("falls back when the 422 detail array is empty", () => {
    const err = axiosErrorWith({ detail: [] }, 422);
    expect(describeError(err, "fallback")).toBe("fallback");
  });

  it("falls back when the 422 detail entry has no string msg", () => {
    const err = axiosErrorWith({ detail: [{ loc: ["body"] }] }, 422);
    expect(describeError(err, "fallback")).toBe("fallback");
  });

  it("falls back when `detail` is an unexpected type", () => {
    const err = axiosErrorWith({ detail: { nested: true } });
    expect(describeError(err, "fallback")).toBe("fallback");
  });
});
