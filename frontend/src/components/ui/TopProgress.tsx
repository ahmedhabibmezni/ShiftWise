export function TopProgress({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div
      aria-hidden
      className="fixed top-0 left-0 right-0 h-[2px] z-50 overflow-hidden"
      style={{ backgroundColor: "var(--accent-tint)" }}
    >
      <div
        className="absolute top-0 left-0 h-full w-1/3"
        style={{
          background:
            "linear-gradient(90deg, transparent, var(--accent-primary), var(--accent-light), transparent)",
          animation: "shiftwise-topbar 1.2s linear infinite",
        }}
      />
    </div>
  );
}
