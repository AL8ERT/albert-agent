type BrandLogoProps = {
  size?: number
}

export function BrandLogo({ size = 26 }: BrandLogoProps) {
  return (
    <svg
      className="header-logo"
      width={size}
      height={size}
      viewBox="16.5 21.5 31 31"
      role="img"
      aria-label="Albert Agent"
    >
      <circle cx="32" cy="37" r="13.5" fill="currentColor" />
      <rect
        x="21.5"
        y="33.8"
        width="8.3"
        height="6.4"
        rx="2"
        fill="var(--panel)"
      />
      <rect
        x="34.2"
        y="33.8"
        width="8.3"
        height="6.4"
        rx="2"
        fill="var(--panel)"
      />
      <path
        d="M29.8 35.4 Q32 34.2 34.2 35.4"
        fill="none"
        stroke="var(--panel)"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <path
        d="M21.9 34.7 L19 35.3 M42.1 34.7 L45 35.3"
        fill="none"
        stroke="var(--panel)"
        strokeWidth="2.2"
        strokeLinecap="round"
      />
    </svg>
  )
}
