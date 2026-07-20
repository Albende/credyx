import React from 'react';
import { Composition, registerRoot } from 'remotion';
import { HeroComposition } from './HeroComposition';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="Hero"
        component={HeroComposition}
        durationInFrames={240}
        fps={30}
        width={1920}
        height={1080}
      />
    </>
  );
};

registerRoot(RemotionRoot);
