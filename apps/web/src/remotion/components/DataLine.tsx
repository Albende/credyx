import React from 'react';
import { useCurrentFrame, interpolate } from 'remotion';
import { theme } from '../theme';

type Props = {
  fromX: number;
  fromY: number;
  toX: number;
  toY: number;
  startFrame: number;
  durationFrames?: number;
};

export const DataLine: React.FC<Props> = ({
  fromX,
  fromY,
  toX,
  toY,
  startFrame,
  durationFrames = 60,
}) => {
  const frame = useCurrentFrame();

  const cx = (fromX + toX) / 2;
  const cy = (fromY + toY) / 2 - 80;
  const path = `M ${fromX} ${fromY} Q ${cx} ${cy} ${toX} ${toY}`;

  const approxLen = Math.hypot(toX - fromX, toY - fromY) * 1.15;

  const progress = interpolate(
    frame,
    [startFrame, startFrame + durationFrames],
    [0, 1],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  const opacity = interpolate(
    frame,
    [startFrame, startFrame + 10, startFrame + durationFrames - 10, startFrame + durationFrames],
    [0, 1, 1, 0.6],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  const dashLen = 32;
  const gapLen = approxLen - dashLen;
  const offset = -progress * approxLen;

  return (
    <g opacity={opacity}>
      <path
        d={path}
        stroke={theme.brand.primary}
        strokeWidth={1}
        fill="none"
        opacity={0.25}
      />
      <path
        d={path}
        stroke={theme.accent}
        strokeWidth={2}
        fill="none"
        strokeDasharray={`${dashLen} ${gapLen}`}
        strokeDashoffset={offset}
        strokeLinecap="round"
        style={{ filter: `drop-shadow(0 0 4px ${theme.accent})` }}
      />
    </g>
  );
};
