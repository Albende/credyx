import React from 'react';
import { useCurrentFrame, interpolate } from 'remotion';
import { theme } from '../theme';

function seededRand(seed: number): () => number {
  let s = seed;
  return () => {
    s = (s * 9301 + 49297) % 233280;
    return s / 233280;
  };
}

type Dot = { x: number; y: number; r: number; opacity: number };

const WIDTH = 1920;
const HEIGHT = 1080;
const MAP_CX = WIDTH / 2;
const MAP_CY = HEIGHT / 2 - 40;
const MAP_RX = 820;
const MAP_RY = 420;

function generateMapDots(): Dot[] {
  const rand = seededRand(1337);
  const dots: Dot[] = [];
  let attempts = 0;
  while (dots.length < 600 && attempts < 5000) {
    attempts++;
    const x = rand() * WIDTH;
    const y = rand() * HEIGHT;
    const nx = (x - MAP_CX) / MAP_RX;
    const ny = (y - MAP_CY) / MAP_RY;
    if (nx * nx + ny * ny <= 1) {
      dots.push({
        x,
        y,
        r: 1.5 + rand() * 1.5,
        opacity: 0.15 + rand() * 0.35,
      });
    }
  }
  return dots;
}

const MAP_DOTS = generateMapDots();

export type Country = {
  code: string;
  name: string;
  x: number;
  y: number;
  appearFrame: number;
};

export const COUNTRIES: Country[] = [
  { code: 'US', name: 'United States', x: 460, y: 460, appearFrame: 30 },
  { code: 'GB', name: 'United Kingdom', x: 920, y: 380, appearFrame: 38 },
  { code: 'FR', name: 'France', x: 950, y: 460, appearFrame: 46 },
  { code: 'DE', name: 'Germany', x: 1000, y: 420, appearFrame: 54 },
  { code: 'ES', name: 'Spain', x: 910, y: 510, appearFrame: 62 },
  { code: 'IT', name: 'Italy', x: 1010, y: 490, appearFrame: 70 },
  { code: 'NO', name: 'Norway', x: 1000, y: 320, appearFrame: 78 },
  { code: 'FI', name: 'Finland', x: 1060, y: 320, appearFrame: 86 },
  { code: 'EE', name: 'Estonia', x: 1080, y: 360, appearFrame: 94 },
  { code: 'CZ', name: 'Czechia', x: 1030, y: 440, appearFrame: 102 },
  { code: 'TR', name: 'Türkiye', x: 1130, y: 510, appearFrame: 110 },
  { code: 'AZ', name: 'Azerbaijan', x: 1200, y: 500, appearFrame: 118 },
];

export const CENTER_X = WIDTH / 2;
export const CENTER_Y = HEIGHT / 2 + 60;

export const WorldMap: React.FC = () => {
  const frame = useCurrentFrame();

  const mapOpacity = interpolate(frame, [30, 70], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <svg
      width={WIDTH}
      height={HEIGHT}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      style={{ position: 'absolute', inset: 0 }}
    >
      <g opacity={mapOpacity}>
        {MAP_DOTS.map((d, i) => (
          <circle
            key={i}
            cx={d.x}
            cy={d.y}
            r={d.r}
            fill={theme.fg.muted}
            opacity={d.opacity}
          />
        ))}
      </g>
      {COUNTRIES.map((c) => {
        const t = interpolate(
          frame,
          [c.appearFrame, c.appearFrame + 12],
          [0, 1],
          { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
        );
        const pulse =
          0.85 +
          0.15 *
            Math.sin(((frame - c.appearFrame) / 30) * Math.PI * 2);
        const r = 6 * t * (frame >= c.appearFrame ? pulse : 1);
        return (
          <g key={c.code}>
            <circle
              cx={c.x}
              cy={c.y}
              r={r * 2.4}
              fill={theme.accent}
              opacity={0.18 * t}
            />
            <circle
              cx={c.x}
              cy={c.y}
              r={r}
              fill={theme.accent}
              opacity={t}
              style={{
                filter: `drop-shadow(0 0 8px ${theme.accent})`,
              }}
            />
          </g>
        );
      })}
    </svg>
  );
};
