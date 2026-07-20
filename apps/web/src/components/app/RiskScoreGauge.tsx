"use client";

interface RiskScoreGaugeProps {
  score: number;
  recommendation: "APPROVE" | "REVIEW" | "REJECT";
  confidence?: number;
  size?: number;
}

const RECOMMENDATION_META: Record<
  RiskScoreGaugeProps["recommendation"],
  { color: string; label: string; ring: string }
> = {
  APPROVE: { color: "#10b981", label: "Approve", ring: "ring-success/30" },
  REVIEW: { color: "#f59e0b", label: "Review", ring: "ring-warning/30" },
  REJECT: { color: "#ef4444", label: "Reject", ring: "ring-danger/30" },
};

export function RiskScoreGauge({ score, recommendation, confidence, size = 220 }: RiskScoreGaugeProps) {
  const clamped = Math.max(0, Math.min(100, score));
  const radius = size / 2 - 14;
  const cx = size / 2;
  const cy = size / 2 + 6;
  const circumference = Math.PI * radius;
  const filled = (clamped / 100) * circumference;
  const meta = RECOMMENDATION_META[recommendation];

  const arc = (startAngle: number, endAngle: number) => {
    const start = polar(cx, cy, radius, startAngle);
    const end = polar(cx, cy, radius, endAngle);
    const largeArc = endAngle - startAngle <= 180 ? 0 : 1;
    return `M ${start.x} ${start.y} A ${radius} ${radius} 0 ${largeArc} 1 ${end.x} ${end.y}`;
  };

  return (
    <div className="relative flex flex-col items-center">
      <div
        aria-hidden
        className="pointer-events-none absolute -inset-6 -z-10"
        style={{
          background: `radial-gradient(60% 55% at 50% 50%, ${meta.color}22 0%, ${meta.color}10 35%, transparent 70%)`,
          filter: "blur(8px)",
        }}
      />
      <svg width={size} height={size * 0.62} viewBox={`0 0 ${size} ${size * 0.62 + 8}`}>
        <defs>
          <linearGradient id="risk-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#ef4444" />
            <stop offset="50%" stopColor="#f59e0b" />
            <stop offset="100%" stopColor="#10b981" />
          </linearGradient>
        </defs>

        <path d={arc(180, 360)} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={14} strokeLinecap="round" />
        <path
          d={arc(180, 360)}
          fill="none"
          stroke="url(#risk-gradient)"
          strokeWidth={14}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
        />

        <text
          x={cx}
          y={cy - 4}
          textAnchor="middle"
          className="font-display"
          style={{ fontSize: size * 0.28, fontWeight: 700, fill: meta.color }}
        >
          {clamped}
        </text>
        <text
          x={cx}
          y={cy + size * 0.085}
          textAnchor="middle"
          style={{ fontSize: 11, fill: "rgba(255,255,255,0.5)", letterSpacing: 1 }}
        >
          / 100
        </text>
      </svg>

      <div className="-mt-2 flex flex-col items-center gap-1">
        <span
          className="rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wider ring-1 ring-inset"
          style={{ color: meta.color, background: `${meta.color}15`, borderColor: meta.color }}
        >
          {meta.label}
        </span>
        {confidence !== undefined && (
          <span className="text-[10px] uppercase tracking-wider text-fg-subtle">
            Confidence {Math.round(confidence * 100)}%
          </span>
        )}
      </div>
    </div>
  );
}

function polar(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = ((angleDeg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}
