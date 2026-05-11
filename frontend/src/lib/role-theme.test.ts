import { describe, expect, it } from "vitest";
import { ROLE_THEMES, getRoleTheme } from "./role-theme";

describe("getRoleTheme", () => {
  it("returns the super_admin theme for known role name", () => {
    const t = getRoleTheme("super_admin");
    expect(t.label).toBe("SUPER ADMIN");
    expect(t.role).toBe("super_admin");
    expect(t.accentColor).toContain("var(--err)");
  });

  it("returns the admin theme with the signal accent", () => {
    const t = getRoleTheme("admin");
    expect(t.label).toBe("ADMINISTRATOR");
    expect(t.accentColor).toContain("var(--signal)");
  });

  it("returns the user theme with the ok accent", () => {
    const t = getRoleTheme("user");
    expect(t.label).toBe("USER");
    expect(t.accentColor).toContain("var(--ok)");
  });

  it("returns the viewer theme with the info accent", () => {
    const t = getRoleTheme("viewer");
    expect(t.label).toBe("VIEWER");
    expect(t.accentColor).toContain("var(--info)");
  });

  it("falls back to MEMBER for null / unknown roles", () => {
    expect(getRoleTheme(null).label).toBe("MEMBER");
    expect(getRoleTheme(undefined).label).toBe("MEMBER");
    expect(getRoleTheme("custom-op").label).toBe("MEMBER");
  });

  it("each theme has a distinct accentColor token", () => {
    const colors = Object.values(ROLE_THEMES).map((t) => t.accentColor);
    expect(new Set(colors).size).toBe(colors.length);
  });
});
