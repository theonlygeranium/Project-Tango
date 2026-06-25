import { type AgentState, BarVisualizer, type TrackReference } from '@livekit/components-react';
import { cn } from '@/lib/utils';

interface AgentAudioTileProps {
  state: AgentState;
  audioTrack: TrackReference;
  isConnecting?: boolean;
  isError?: boolean;
  className?: string;
}

export const AgentTile = ({
  state,
  audioTrack,
  isConnecting = false,
  isError = false,
  className,
  ref,
}: React.ComponentProps<'div'> & AgentAudioTileProps) => {
  const visualState = isError ? 'error' : isConnecting ? 'connecting' : state;

  return (
    <div ref={ref} className={cn('relative', className)}>
      <BarVisualizer
        barCount={5}
        state={state}
        options={{ minHeight: 5 }}
        trackRef={audioTrack}
        data-agent-state={visualState}
        className={cn(
          'relative flex aspect-square w-40 items-center justify-center gap-1 rounded-full border transition-[background-color,border-color,box-shadow,scale] duration-500 ease-out',
          visualState === 'connecting' &&
            'border-separatorAccent bg-bgAccentPrimary/80 scale-95 shadow-[0_0_34px_rgba(31,213,249,0.22)]',
          visualState === 'listening' &&
            'border-separatorSuccess bg-bgSuccess/35 scale-100 shadow-[0_0_38px_rgba(59,201,129,0.22)]',
          visualState === 'thinking' &&
            'border-separatorModerate bg-bgModerate/40 scale-105 animate-pulse shadow-[0_0_44px_rgba(255,183,82,0.28)]',
          visualState === 'speaking' &&
            'border-separatorAccent bg-bgAccent/50 scale-110 shadow-[0_0_54px_rgba(110,157,254,0.32)]',
          visualState === 'error' &&
            'border-separatorSerious bg-bgSerious/70 animate-orb-error-shake shadow-[0_0_42px_rgba(255,117,102,0.35)]'
        )}
      >
        <span
          className={cn([
            'bg-muted min-h-4 w-4 rounded-full',
            'origin-center transition-[background-color,height,scale] duration-250 ease-linear',
            'data-[lk-highlighted=true]:bg-foreground data-[lk-muted=true]:bg-muted',
            visualState === 'speaking' && 'data-[lk-highlighted=true]:scale-125',
          ])}
        />
      </BarVisualizer>
      {isConnecting && (
        <>
          <span className="border-fgAccent/70 absolute inset-0 animate-spin rounded-full border-2 border-t-transparent" />
          <span className="text-fg2 absolute -bottom-9 left-1/2 -translate-x-1/2 text-sm font-medium whitespace-nowrap">
            Connecting...
          </span>
        </>
      )}
    </div>
  );
};
