import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate, spring } from 'remotion';
import { theme } from '../theme';

type Ratio = {
  label: string;
  target: number;
  format: (v: number) => string;
};

const RATIOS: Ratio[] = [
  { label: 'Current Ratio', target: 1.85, format: (v) => v.toFixed(2) },
  { label: 'D / E', target: 0.42, format: (v) => v.toFixed(2) },
  { label: 'ROE', target: 14.2, format: (v) => `${v.toFixed(1)}%` },
  { label: 'EBITDA Margin', target: 18, format: (v) => `${v.toFixed(0)}%` },
];

const APPEAR_FRAME = 150;
const TICK_DURATION = 50;

export const RatioCard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const cardSpring = spring({
    frame: frame - APPEAR_FRAME,
    fps,
    from: 0,
    to: 1,
    config: { damping: 100, stiffness: 150 },
  });

  const opacity = interpolate(frame, [APPEAR_FRAME, APPEAR_FRAME + 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const exitOpacity = interpolate(frame, [230, 240], [1, 0.4], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const scale = 0.92 + cardSpring * 0.08;

  return (
    <div
      style={{
        position: 'absolute',
        top: 220,
        left: '50%',
        transform: `translateX(-50%) scale(${scale})`,
        opacity: opacity * exitOpacity,
        width: 760,
        padding: 36,
        borderRadius: 24,
        background: 'rgba(255, 255, 255, 0.04)',
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
        border: `1px solid rgba(255, 255, 255, 0.08)`,
        boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
        display: 'flex',
        flexDirection: 'column',
        gap: 18,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <div
        style={{
          fontSize: 16,
          letterSpacing: 2,
          color: theme.fg.muted,
          textTransform: 'uppercase',
        }}
      >
        Financial Ratios — Q4 2025
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: 20,
        }}
      >
        {RATIOS.map((r, i) => {
          const startFrame = APPEAR_FRAME + 10 + i * 6;
          const t = interpolate(
            frame,
            [startFrame, startFrame + TICK_DURATION],
            [0, 1],
            { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
          );
          const eased = 1 - Math.pow(1 - t, 3);
          const value = r.target * eased;
          return (
            <div
              key={r.label}
              style={{
                background: 'rgba(255,255,255,0.03)',
                borderRadius: 14,
                padding: '18px 22px',
                border: '1px solid rgba(255,255,255,0.05)',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
              }}
            >
              <div
                style={{
                  fontSize: 14,
                  color: theme.fg.muted,
                  letterSpacing: 1,
                  textTransform: 'uppercase',
                }}
              >
                {r.label}
              </div>
              <div
                style={{
                  fontSize: 44,
                  fontWeight: 700,
                  color: theme.fg.default,
                  fontVariantNumeric: 'tabular-nums',
                  letterSpacing: -1,
                }}
              >
                {r.format(value)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
