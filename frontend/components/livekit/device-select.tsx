'use client';

import { useCallback, useEffect } from 'react';
import { cva } from 'class-variance-authority';
import { LocalAudioTrack, LocalVideoTrack } from 'livekit-client';
import { useMaybeRoomContext, useMediaDeviceSelect } from '@livekit/components-react';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';

type DeviceSelectProps = React.ComponentProps<typeof SelectTrigger> & {
  kind: MediaDeviceKind;
  track?: LocalAudioTrack | LocalVideoTrack | undefined;
  requestPermissions?: boolean;
  onMediaDeviceError?: (error: Error) => void;
  initialSelection?: string;
  onActiveDeviceChange?: (deviceId: string) => void;
  onDeviceListChange?: (devices: MediaDeviceInfo[]) => void;
  variant?: 'default' | 'small';
};

const selectVariants = cva(
  [
    'w-full rounded-full px-3 py-2 text-sm cursor-pointer',
    'disabled:not-allowed hover:bg-button-hover focus:bg-button-hover',
  ],
  {
    variants: {
      size: {
        default: 'w-[180px]',
        sm: 'w-auto',
      },
    },
    defaultVariants: {
      size: 'default',
    },
  }
);

export function DeviceSelect({
  kind,
  track,
  requestPermissions,
  onMediaDeviceError,
  onActiveDeviceChange,
  onDeviceListChange,
  className,
  size = 'default',
  title,
  ...triggerProps
}: DeviceSelectProps) {
  const room = useMaybeRoomContext();
  const { devices, activeDeviceId, setActiveMediaDevice } = useMediaDeviceSelect({
    kind,
    room,
    track,
    requestPermissions,
    onError: onMediaDeviceError,
  });
  const label =
    triggerProps['aria-label'] ?? (kind === 'audioinput' ? 'Choose microphone' : 'Choose camera');
  const handleValueChange = useCallback(
    async (deviceId: string) => {
      await setActiveMediaDevice(deviceId);
      onActiveDeviceChange?.(deviceId);
    },
    [onActiveDeviceChange, setActiveMediaDevice]
  );

  useEffect(() => {
    onDeviceListChange?.(devices);
  }, [devices, onDeviceListChange]);

  return (
    <Select value={activeDeviceId} onValueChange={handleValueChange}>
      <SelectTrigger
        className={cn(selectVariants({ size }), className)}
        title={title ?? label}
        {...triggerProps}
        aria-label={label}
      >
        {size !== 'sm' && (
          <SelectValue className="font-mono text-sm" placeholder={`Select a ${kind}`} />
        )}
      </SelectTrigger>
      <SelectContent>
        {devices.map((device, index) => (
          <SelectItem key={device.deviceId} value={device.deviceId} className="font-mono text-xs">
            {device.label || `Device ${index + 1}`}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
