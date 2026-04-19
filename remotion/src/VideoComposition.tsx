import React from "react";
import { AbsoluteFill, Audio, OffthreadVideo, Sequence } from "remotion";

export interface Scene {
  url: string;
  durationFrames: number;
}

export interface VideoProps {
  audioUrl: string;
  audioDurationSec: number;
  scenes: Scene[];
}

export const VideoComposition: React.FC<VideoProps> = ({ audioUrl, scenes }) => {
  let cursor = 0;

  return (
    <AbsoluteFill style={{ backgroundColor: "#000" }}>
      {scenes.map((scene, i) => {
        const from = cursor;
        cursor += scene.durationFrames;
        return (
          <Sequence key={i} from={from} durationInFrames={scene.durationFrames}>
            <AbsoluteFill>
              <OffthreadVideo
                src={scene.url}
                loop
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
            </AbsoluteFill>
          </Sequence>
        );
      })}
      <Audio src={audioUrl} />
    </AbsoluteFill>
  );
};
