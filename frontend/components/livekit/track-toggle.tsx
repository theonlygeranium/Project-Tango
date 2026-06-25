'use client';

import * as React from 'react';
import { Track } from 'livekit-client';
import { useTrackToggle } from '@livekit/components-react';
import {
  MicrophoneIcon,
  MicrophoneSlashIcon,
  MonitorArrowUpIcon,
  SpinnerIcon,
  VideoCameraIcon,
  VideoCameraSlashIcon,
} from '@phosphor-icons/react/dist/ssr';
import { Toggle } from '@/components/ui/toggle';
import { cn } from '@/lib/utils';

export type TrackToggleProps = React.ComponentProps<typeof Toggle> & {
  source: Parameters<typeof useTrackToggle>[0]['source'];
  pending?: boolean;
};

function getSourceIcon(source: Track.Source, enabled: boolean, pending = false) {
  if (pending) {
    return SpinnerIcon;
  }

  switch (source) {
    case Track.Source.Microphone:
      return enabled ? MicrophoneIcon : MicrophoneSlashIcon;
    case Track.Source.Camera:
      return enabled ? VideoCameraIcon : VideoCameraSlashIcon;
    case Track.Source.ScreenShare:
      return MonitorArrowUpIcon;
    default:
      return React.Fragment;
  }
}

function getSourceLabel(source: Track.Source, enabled: boolean, pending = false) {
  if (pending) {
    return 'Preparing media';
  }

  switch (source) {
    case Track.Source.Microphone:
      return enabled ? 'Mute microphone' : 'Unmute microphone';
    case Track.Source.Camera:
      return enabled ? 'Stop camera preview' : 'Share camera preview';
    case Track.Source.ScreenShare:
      return enabled ? 'Stop screen share' : 'Share screen';
    default:
      return 'Toggle media';
  }
}

export function TrackToggle({
  source,
  pressed,
  pending,
  className,
  title,
  ...props
}: TrackToggleProps) {
  const enabled = pressed ?? false;
  const IconComponent = getSourceIcon(source, enabled, pending);
  const label = props['aria-label'] ?? getSourceLabel(source, enabled, pending);

  return (
    <Toggle
      pressed={pressed}
      title={title ?? label}
      className={cn(className)}
      {...props}
      aria-label={label}
    >
      <IconComponent weight="bold" className={cn(pending && 'animate-spin')} />
      {props.children}
    </Toggle>
  );
}
