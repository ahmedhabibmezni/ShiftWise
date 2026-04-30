export function TopProgress({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div
      aria-hidden
      className="fixed top-0 left-0 right-0 h-px z-50 overflow-hidden"
      style={{ backgroundColor: "color-mix(in srgb, var(--signal) 25%, transparent)" }}
    >
      <div
        className="absolute top-0 left-0 h-px w-1/3"
        style={{
          backgroundColor: "var(--signal)",
          animation: "shiftwise-topbar 1.2s linear infinite",
        }}
      />
    </div>
  );
}
