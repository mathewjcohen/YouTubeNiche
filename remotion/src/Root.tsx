import React from "react";
import { Composition } from "remotion";
import { VideoComposition } from "./VideoComposition";
import type { VideoProps } from "./VideoComposition";

const DEFAULT_PROPS: VideoProps = {
  audioUrl: "",
  audioDurationSec: 60,
  scenes: [],
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="VideoComposition"
      component={VideoComposition}
      fps={24}
      width={1920}
      height={1080}
      defaultProps={DEFAULT_PROPS}
      calculateMetadata={({ props }) => ({
        durationInFrames: Math.max(Math.ceil(props.audioDurationSec * 24), 24),
        fps: 24,
        width: 1920,
        height: 1080,
      })}
    />
  );
};
