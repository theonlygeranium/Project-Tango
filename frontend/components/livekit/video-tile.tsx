import React from 'react';
import { motion } from 'motion/react';
import { VideoTrack } from '@livekit/components-react';
import { cn } from '@/lib/utils';

const MotionVideoTrack = motion.create(VideoTrack);

export const VideoTile = ({
  trackRef,
  label,
  fit = 'cover',
  className,
  ref,
}: React.ComponentProps<'div'> &
  React.ComponentProps<typeof VideoTrack> & {
    fit?: 'contain' | 'cover';
    label?: string;
  }) => {
  return (
    <div ref={ref} className={cn('bg-muted relative overflow-hidden rounded-md', className)}>
      <MotionVideoTrack
        trackRef={trackRef}
        width={trackRef?.publication.dimensions?.width ?? 0}
        height={trackRef?.publication.dimensions?.height ?? 0}
        className={cn('h-full w-full', fit === 'contain' ? 'object-contain' : 'object-cover')}
      />
      {label && (
        <span className="absolute right-1.5 bottom-1.5 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[0.55rem] font-bold tracking-wide text-white/80 uppercase">
          {label}
        </span>
      )}
    </div>
  );
};
