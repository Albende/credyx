import Link from "next/link";
import { cn } from "@/lib/cn";

/**
 * Credyx seal + wordmark. The mark is an engraved rosette —
 * concentric rings with radial ticks, like a banknote seal — with a
 * gold-leaf X monogram at the center. Wordmark set in the display serif.
 */
export function Logo({
  href = "/",
  className,
  showText = true,
}: {
  href?: string | null;
  className?: string;
  showText?: boolean;
}) {
  const inner = (
    <span className={cn("flex items-center gap-2.5", className)}>
      <span className="grid h-7 w-7 place-items-center rounded-[6px] border border-border-strong bg-bg-inset">
        <svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden>
          <circle cx="12" cy="12" r="9.5" stroke="hsl(var(--brand-primary))" strokeWidth="1" />
          <circle cx="12" cy="12" r="6.5" stroke="hsl(var(--brand-primary))" strokeWidth="1" />
          <g stroke="hsl(var(--fg-subtle))" strokeWidth="1">
            {Array.from({ length: 12 }, (_, i) => {
              const a = (i * Math.PI) / 6;
              const cos = Math.cos(a);
              const sin = Math.sin(a);
              return (
                <line
                  key={i}
                  x1={(12 + 6.5 * cos).toFixed(2)}
                  y1={(12 + 6.5 * sin).toFixed(2)}
                  x2={(12 + 9.5 * cos).toFixed(2)}
                  y2={(12 + 9.5 * sin).toFixed(2)}
                />
              );
            })}
          </g>
          <g
            stroke="hsl(var(--brand-secondary))"
            strokeWidth="1.9"
            strokeLinecap="round"
          >
            <line x1="9.7" y1="9.7" x2="14.3" y2="14.3" />
            <line x1="14.3" y1="9.7" x2="9.7" y2="14.3" />
          </g>
        </svg>
      </span>
      {showText && (
        <span className="font-display text-[1.02rem] font-semibold tracking-tight text-fg-default">
          Credyx
        </span>
      )}
    </span>
  );
  if (href === null) return inner;
  return (
    <Link href={href} aria-label="Credyx" className="inline-flex">
      {inner}
    </Link>
  );
}
