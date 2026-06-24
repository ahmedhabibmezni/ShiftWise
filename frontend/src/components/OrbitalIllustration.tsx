/**
 * Decorative SVG used as the bleed-off visual on the Dashboard hero panel.
 * Three nested orbiting ellipses around a glowing core, plus scattered dots.
 *
 * The component is purely visual. It accepts width/height for sizing and
 * renders into the parent container — no internal layout assumptions.
 */
export function OrbitalIllustration({
  className,
}: {
  className?: string;
}) {
  return (

    <svg
      viewBox="0 0 400 300"
      preserveAspectRatio="xMidYMid meet"
      fill="none"
      className={className}
      aria-hidden
    >
      <defs>
        <radialGradient id="sw-orb-core" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#FFC9A8" stopOpacity="0.95" />
          <stop offset="35%" stopColor="#FF7A2F" stopOpacity="0.85" />
          <stop offset="65%" stopColor="#E62600" stopOpacity="0.55" />
          <stop offset="100%" stopColor="#812300" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="sw-orb-ring" x1="0" x2="1">
          <stop offset="0%" stopColor="#FF7A2F" stopOpacity="0.6" />
          <stop offset="50%" stopColor="#3E6FD4" stopOpacity="0.4" />
          <stop offset="100%" stopColor="#1F3F8A" stopOpacity="0.1" />
        </linearGradient>
      </defs>
      {/* Orbiting rings */}
      <ellipse
        cx="240"
        cy="180"
        rx="180"
        ry="60"
        stroke="url(#sw-orb-ring)"
        strokeWidth="1.2"
        transform="rotate(-22 240 180)"
      />
      <ellipse
        cx="240"
        cy="180"
        rx="140"
        ry="45"
        stroke="url(#sw-orb-ring)"
        strokeWidth="1"
        strokeOpacity="0.7"
        transform="rotate(-12 240 180)"
      />
      <ellipse
        cx="240"
        cy="180"
        rx="100"
        ry="32"
        stroke="url(#sw-orb-ring)"
        strokeWidth="1"
        strokeOpacity="0.4"
        transform="rotate(14 240 180)"
      />
      {/* Halo + core orb */}
      <circle cx="240" cy="180" r="120" fill="url(#sw-orb-core)" opacity="0.5" />
      <circle cx="240" cy="180" r="55" fill="url(#sw-orb-core)" />
      <circle cx="240" cy="180" r="30" fill="#FFC9A8" fillOpacity="0.5" />
      <circle cx="240" cy="180" r="12" fill="white" fillOpacity="0.9" />
      {/* Scattered dots */}
      <circle cx="402" cy="160" r="4" fill="#3E6FD4" />
      <circle cx="380" cy="220" r="3" fill="#FF7A2F" />
      <circle cx="80" cy="200" r="3" fill="#2ECC8A" />
      <circle cx="120" cy="120" r="2.5" fill="#FFFFFF" fillOpacity="0.6" />
      <circle cx="350" cy="80" r="2" fill="#FFFFFF" fillOpacity="0.4" />
      <circle cx="160" cy="260" r="3" fill="#3E6FD4" fillOpacity="0.6" />
    </svg>

  );
}
