import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate, spring } from 'remotion';
import { theme } from '../theme';

const APPEAR_FRAME = 200;
const TARGET_SCORE = 78;
const RADIUS = 90;
const STROKE = 14;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export const ScoreDial: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const dialSpring = spring({
    frame: frame - APPEAR_FRAME,
    fps,
    from: 0,
    to: 1,
    config: { damping: 18, stiffness: 90 },
  });

  const score = TARGET_SCORE * dialSpring;
  const dashOffset = CIRCUMFERENCE * (1 - score / 100);

  const containerOpacity = interpolate(
    frame,
    [APPEAR_FRAME, APPEAR_FRAME + 15],
    [0, 1],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  const stampSpring = spring({
    frame: frame - 230,
    fps,
    from: 0.5,
    to: 1,
    config: { damping: 12, stiffness: 200 },
  });

  const stampOpacity = interpolate(frame, [230, 238], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const exitOpacity = interpolate(frame, [230, 240], [1, 0.4], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div
      style={{
        position: 'absolute',
        bottom: 90,
        left: '50%',
        transform: 'translateX(-50%)',
        opacity: containerOpacity * exitOpacity,
        display: 'flex',
        alignItems: 'center',
        gap: 48,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <div style={{ position: 'relative', width: 220, height: 220 }}>
        <svg width={220} height={220}>
          <circle
            cx={110}
            cy={110}
            r={RADIUS}
            stroke="rgba(255,255,255,0.08)"
            strokeWidth={STROKE}
            fill="none"
          />
          <circle
            cx={110}
            cy={110}
            r={RADIUS}
            stroke={theme.success}
            strokeWidth={STROKE}
            fill="none"
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={dashOffset}
            transform="rotate(-90 110 110)"
            style={{ filter: `drop-shadow(0 0 12px ${theme.success})` }}
          />
        </svg>
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <div
            style={{
              fontSize: 64,
              fontWeight: 800,
              color: theme.fg.default,
              fontVariantNumeric: 'tabular-nums',
              letterSpacing: -2,
              lineHeight: 1,
            }}
          >
            {Math.round(score)}
          </div>
          <div
            style={{
              fontSize: 12,
              color: theme.fg.muted,
              letterSpacing: 3,
              textTransform: 'uppercase',
              marginTop: 4,
            }}
          >
            Credit Score
          </div>
        </div>
      </div>

      <div
        style={{
          transform: `scale(${stampSpring})`,
          opacity: stampOpacity,
          padding: '18px 36px',
          border: `3px solid ${theme.success}`,
          borderRadius: 12,
          color: theme.success,
          fontSize: 38,
          fontWeight: 800,
          letterSpacing: 6,
          textTransform: 'uppercase',
          boxShadow: `0 0 24px ${theme.success}55`,
        }}
      >
        Approve
      </div>
    </div>
  );
};
