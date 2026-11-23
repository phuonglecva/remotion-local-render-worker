import React from 'react';
import {Composition} from 'remotion';
import {VideoComposition} from './VideoComposition';

export const Root: React.FC = () => (
  <Composition
    id="Main"
    component={VideoComposition}
    durationInFrames={900}
    fps={30}
    width={1080}
    height={1920}
    defaultProps={{
      baseVideoPath: 'jobs/preview/base.mp4',
      durationInFrames: 900,
      fps: 30,
      width: 1080,
      height: 1920,
      timeline: {schema_version: '1.0', layers: []},
    }}
    calculateMetadata={({props}) => ({
      durationInFrames: props.durationInFrames,
      fps: props.fps,
      width: props.width,
      height: props.height,
    })}
  />
);
