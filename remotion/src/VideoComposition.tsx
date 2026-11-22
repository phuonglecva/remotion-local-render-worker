import React from 'react';
import {
  AbsoluteFill,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {Video} from '@remotion/media';

type Cue = {
  id: string;
  type: 'caption' | 'bubble' | 'zoom' | 'flash';
  start: number;
  end: number;
  text?: string | null;
  position?: 'top' | 'center' | 'bottom';
  scale?: number;
  style?: Record<string, string | number | boolean>;
};

type Timeline = {
  schema_version: string;
  layers: Cue[];
};

export type VideoCompositionProps = {
  baseVideoPath: string;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
  timeline: Timeline;
};

const CueOverlay: React.FC<{cue: Cue}> = ({cue}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({frame, fps, config: {damping: 16, stiffness: 180}});
  const opacity = interpolate(frame, [0, 5, 9], [0, 1, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const translateY = interpolate(enter, [0, 1], [24, 0]);
  const fontSize = Number(cue.style?.font_size ?? 66);
  const background = String(
    cue.style?.background ?? (cue.type === 'bubble' ? '#fffdf7' : 'rgba(15, 18, 25, 0.72)'),
  );
  const textColor = String(
    cue.style?.text_color ?? (cue.type === 'bubble' ? '#252525' : '#ffffff'),
  );
  const alignY =
    cue.position === 'top' ? '14%' : cue.position === 'center' ? '48%' : '77%';

  if (cue.type === 'flash') {
    const flashOpacity = interpolate(frame, [0, 2, 7], [0, 0.62, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
    return (
      <AbsoluteFill
        style={{backgroundColor: String(cue.style?.color ?? '#ffffff'), opacity: flashOpacity}}
      />
    );
  }

  if (cue.type === 'zoom') return null;

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'center',
        alignItems: 'center',
        top: alignY,
        height: 'auto',
        paddingLeft: '7%',
        paddingRight: '7%',
        opacity,
        translate: '0px ' + translateY + 'px',
      }}
    >
      <div
        style={{
          maxWidth: '100%',
          padding: cue.type === 'bubble' ? '24px 32px' : '18px 28px',
          borderRadius: cue.type === 'bubble' ? 34 : 22,
          background,
          color: textColor,
          border: cue.type === 'bubble' ? '5px solid #252525' : 'none',
          boxShadow: '0 8px 24px rgba(0,0,0,0.22)',
          fontFamily: '"Be Vietnam Pro", "Noto Sans", Inter, Arial, sans-serif',
          fontSize,
          fontWeight: 800,
          lineHeight: 1.15,
          textAlign: 'center',
          textShadow: cue.type === 'caption' ? '0 2px 8px rgba(0,0,0,0.28)' : 'none',
          whiteSpace: 'pre-wrap',
          overflowWrap: 'anywhere',
        }}
      >
        {cue.text}
      </div>
    </AbsoluteFill>
  );
};

export const VideoComposition: React.FC<VideoCompositionProps> = (props) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const activeZoom = props.timeline.layers.find(
    (cue) =>
      cue.type === 'zoom' &&
      frame >= Math.floor(cue.start * fps) &&
      frame < Math.ceil(cue.end * fps),
  );
  const videoSrc = staticFile(props.baseVideoPath);

  return (
    <AbsoluteFill style={{backgroundColor: '#000000'}}>
      <AbsoluteFill
        style={{
          scale: activeZoom?.scale ?? 1,
          transformOrigin: '50% 50%',
        }}
      >
        <Video
          src={videoSrc}
          volume={1}
          premountFor={fps}
          style={{position: 'absolute', width: '100%', height: '100%'}}
        />
      </AbsoluteFill>
      {props.timeline.layers
        .filter((cue) => cue.type !== 'zoom')
        .map((cue) => {
          const from = Math.max(0, Math.floor(cue.start * fps));
          const to = Math.min(props.durationInFrames, Math.ceil(cue.end * fps));
          const duration = Math.max(1, to - from);
          return (
            <Sequence key={cue.id} from={from} durationInFrames={duration} premountFor={fps}>
              <CueOverlay cue={cue} />
            </Sequence>
          );
        })}
    </AbsoluteFill>
  );
};
