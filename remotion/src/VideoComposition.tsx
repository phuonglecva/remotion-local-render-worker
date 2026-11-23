import React from 'react';
import {
  AbsoluteFill,
  AnimatedImage,
  Img,
  OffthreadVideo,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {Audio, Video} from '@remotion/media';

type Cue = {
  id: string;
  type: 'caption' | 'bubble' | 'zoom' | 'flash' | 'meme' | 'broll';
  start: number;
  end: number;
  text?: string | null;
  asset_id?: string | null;
  position?: 'top' | 'center' | 'bottom';
  scale?: number;
  x?: number | null;
  y?: number | null;
  width?: number | null;
  height?: number | null;
  opacity?: number;
  fit?: 'cover' | 'contain' | 'fill';
  style?: Record<string, string | number | boolean>;
};

type Timeline = {
  schema_version: string;
  layers: Cue[];
};

type AssetSource = {
  src: string;
  mediaType: 'audio' | 'image' | 'gif' | 'video';
};

type DuckingRange = {
  start: number;
  end: number;
  volume: number;
};

type AudioTrack = {
  id: string;
  src: string;
  start: number;
  end: number;
  volume: number;
  fadeIn: number;
  fadeOut: number;
  loop: boolean;
  duckingRanges: DuckingRange[];
};

export type VideoCompositionProps = {
  baseVideoPath: string;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
  timeline: Timeline;
  assets: Record<string, AssetSource>;
  audioTracks: AudioTrack[];
};

const AssetOverlay: React.FC<{
  cue: Cue;
  asset: AssetSource;
}> = ({cue, asset}) => {
  const {width: frameWidth, height: frameHeight} = useVideoConfig();
  const isBroll = cue.type === 'broll';
  const x = cue.x ?? (isBroll ? 0 : 62);
  const y = cue.y ?? (isBroll ? 0 : 62);
  const width = cue.width ?? (isBroll ? 100 : 34);
  const height = cue.height ?? (isBroll ? 100 : 30);
  const fit = cue.fit ?? (isBroll ? 'cover' : 'contain');
  const containerStyle: React.CSSProperties = {
    position: 'absolute',
    left: String(x) + '%',
    top: String(y) + '%',
    width: String(width) + '%',
    height: String(height) + '%',
    opacity: cue.opacity ?? 1,
    overflow: 'hidden',
    borderRadius: isBroll ? 0 : 24,
    boxShadow: isBroll ? 'none' : '0 10px 30px rgba(0,0,0,0.3)',
    zIndex: isBroll ? 5 : 8,
  };
  const pixelWidth = Math.max(1, Math.round((frameWidth * width) / 100));
  const pixelHeight = Math.max(1, Math.round((frameHeight * height) / 100));

  if (asset.mediaType === 'gif') {
    return (
      <div style={containerStyle}>
        <AnimatedImage
          src={staticFile(asset.src)}
          width={pixelWidth}
          height={pixelHeight}
          fit={fit}
          loopBehavior="loop"
          style={{width: '100%', height: '100%'}}
        />
      </div>
    );
  }

  if (asset.mediaType === 'video') {
    return (
      <div style={containerStyle}>
        <OffthreadVideo
          src={staticFile(asset.src)}
          muted
          volume={0}
          style={{width: '100%', height: '100%', objectFit: fit}}
        />
      </div>
    );
  }

  return (
    <div style={containerStyle}>
      <Img
        src={staticFile(asset.src)}
        style={{width: '100%', height: '100%', objectFit: fit}}
      />
    </div>
  );
};

const AudioLayer: React.FC<{track: AudioTrack}> = ({track}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const localTime = frame / fps;
  const globalTime = track.start + localTime;
  const duration = Math.max(0, track.end - track.start);
  let gain = track.volume;

  if (track.fadeIn > 0) {
    const fadeIn = Math.min(track.fadeIn, duration);
    gain *= interpolate(localTime, [0, fadeIn], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
  }
  if (track.fadeOut > 0) {
    const fadeOut = Math.min(track.fadeOut, duration);
    gain *= interpolate(localTime, [duration - fadeOut, duration], [1, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
  }
  for (const range of track.duckingRanges) {
    const attack = Math.min(0.08, (range.end - range.start) / 4);
    const release = Math.min(0.18, (range.end - range.start) / 4);
    gain *= interpolate(
      globalTime,
      [range.start - attack, range.start, range.end, range.end + release],
      [1, range.volume, range.volume, 1],
      {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
    );
  }

  return (
    <Audio
      src={staticFile(track.src)}
      volume={Math.max(0, gain)}
      loop={track.loop}
      premountFor={fps}
    />
  );
};

const CueOverlay: React.FC<{
  cue: Cue;
  assets: Record<string, AssetSource>;
}> = ({cue, assets}) => {
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

  if (cue.type === 'meme' || cue.type === 'broll') {
    const asset = cue.asset_id ? assets[cue.asset_id] : undefined;
    if (!asset) return null;
    return <AssetOverlay cue={cue} asset={asset} />;
  }

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
              <CueOverlay cue={cue} assets={props.assets ?? {}} />
            </Sequence>
          );
        })}
      {props.audioTracks?.map((track) => {
        const from = Math.max(0, Math.floor(track.start * fps));
        const to = Math.min(props.durationInFrames, Math.ceil(track.end * fps));
        const duration = Math.max(1, to - from);
        return (
          <Sequence key={'audio-' + track.id} from={from} durationInFrames={duration} premountFor={fps}>
            <AudioLayer track={track} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
