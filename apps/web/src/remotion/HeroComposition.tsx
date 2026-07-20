import React from 'react';
import {
  AbsoluteFill,
  Sequence,
  useCurrentFrame,
  interpolate,
} from 'remotion';
import { theme } from './theme';
import {
  WorldMap,
  COUNTRIES,
  CENTER_X,
  CENTER_Y,
} from './components/WorldMap';
import { DataLine } from './components/DataLine';
import { RatioCard } from './components/RatioCard';
import { ScoreDial } from './components/ScoreDial';

const WIDTH = 1920;
const HEIGHT = 1080;

const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const fadeIn = interpolate(frame, [0, 30], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const exit = interpolate(frame, [230, 240], [1, 0.92], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const pan = interpolate(frame, [0, 240], [0, -20], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill
      style={{
        background: theme.bg.base,
        opacity: fadeIn * exit,
      }}
    >
      <AbsoluteFill
        style={{
          background: `radial-gradient(900px 600px at 30% 40%, ${theme.brand.primary}33, transparent 60%), radial-gradient(900px 700px at 75% 70%, ${theme.accent}26, transparent 65%), radial-gradient(700px 500px at 60% 20%, ${theme.brand.secondary}1f, transparent 60%)`,
        }}
      />
      <AbsoluteFill
        style={{
          transform: `translateX(${pan}px)`,
          backgroundImage: `linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)`,
          backgroundSize: '64px 64px',
          opacity: 0.4,
        }}
      />
    </AbsoluteFill>
  );
};

const Title: React.FC = () => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [10, 40, 220, 240], [0, 1, 1, 0.3], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const y = interpolate(frame, [10, 40], [12, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'absolute',
        top: 80,
        left: 0,
        right: 0,
        textAlign: 'center',
        opacity,
        transform: `translateY(${y}px)`,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <div
        style={{
          fontSize: 14,
          letterSpacing: 6,
          color: theme.accent,
          textTransform: 'uppercase',
          marginBottom: 12,
        }}
      >
        Credit Intelligence — Global Coverage
      </div>
      <div
        style={{
          fontSize: 56,
          fontWeight: 800,
          color: theme.fg.default,
          letterSpacing: -1.5,
          lineHeight: 1.1,
        }}
      >
        Real registry data. Real risk signals.
      </div>
    </div>
  );
};

const DataFlow: React.FC = () => {
  return (
    <svg
      width={WIDTH}
      height={HEIGHT}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      style={{ position: 'absolute', inset: 0 }}
    >
      {COUNTRIES.map((c, i) => (
        <DataLine
          key={c.code}
          fromX={c.x}
          fromY={c.y}
          toX={CENTER_X}
          toY={CENTER_Y}
          startFrame={90 + i * 5}
          durationFrames={70}
        />
      ))}
    </svg>
  );
};

export const HeroComposition: React.FC = () => {
  return (
    <AbsoluteFill style={{ background: theme.bg.base }}>
      <Background />
      <Title />
      <Sequence from={30} durationInFrames={210}>
        <WorldMap />
      </Sequence>
      <Sequence from={90} durationInFrames={150}>
        <DataFlow />
      </Sequence>
      <Sequence from={150} durationInFrames={90}>
        <RatioCard />
      </Sequence>
      <Sequence from={200} durationInFrames={40}>
        <ScoreDial />
      </Sequence>
    </AbsoluteFill>
  );
};
