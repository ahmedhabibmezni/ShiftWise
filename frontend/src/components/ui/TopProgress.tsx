import { cn } from "@/lib/cn";

type Props = {
  active?: boolean;
  className?: string;
};

export function TopProgress({ active, className }: Props) {
  return (
    <div
      aria-hidden
      className={cn(
        "fixed top-0 left-0 right-0 z-50 h-px overflow-hidden pointer-events-none",
        "transition-opacity duration-[120ms]",
        active ? "opacity-100" : "opacity-0",
        className,
      )}
    >
      <div
        className={cn(
          "h-full bg-signal",
          active && "[animation:shiftwise-topbar_1.2s_ease-in-out_infinite]",
        )}
      />
      <style>{`
        @keyframes shiftwise-topbar {
          0%   { transform: translateX(-100%); width: 30%; }
          50%  { transform: translateX(50%);   width: 50%; }
          100% { transform: translateX(200%);  width: 30%; }
        }
      `}</style>
    </div>
  );
}
