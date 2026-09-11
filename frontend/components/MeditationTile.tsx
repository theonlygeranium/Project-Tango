'use client';

import { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

export function MeditationTile() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onLoadedMetadata = () => {
      setDuration(audio.duration);
      setIsLoading(false);
    };
    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    const onEnded = () => {
      setIsPlaying(false);
      setCurrentTime(0);
    };
    const onWaiting = () => setIsLoading(true);
    const onCanPlay = () => setIsLoading(false);

    audio.addEventListener('loadedmetadata', onLoadedMetadata);
    audio.addEventListener('timeupdate', onTimeUpdate);
    audio.addEventListener('play', onPlay);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('ended', onEnded);
    audio.addEventListener('waiting', onWaiting);
    audio.addEventListener('canplay', onCanPlay);

    return () => {
      audio.removeEventListener('loadedmetadata', onLoadedMetadata);
      audio.removeEventListener('timeupdate', onTimeUpdate);
      audio.removeEventListener('play', onPlay);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('ended', onEnded);
      audio.removeEventListener('waiting', onWaiting);
      audio.removeEventListener('canplay', onCanPlay);
    };
  }, []);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
    } else {
      setIsLoading(true);
      audio.play().catch(() => setIsLoading(false));
    }
  };

  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    const audio = audioRef.current;
    if (!audio || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    audio.currentTime = ratio * duration;
  };

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div
      className={cn(
        'bg-background/70 group relative flex w-full flex-col rounded-lg border shadow-sm backdrop-blur-md transition',
        'border-indigo-500/40 hover:border-indigo-500/70 hover:bg-indigo-500/5'
      )}
    >
      <audio ref={audioRef} preload="metadata" src="/api/meditation-audio" />

      {/* Tile header — looks like a persona tile */}
      <div className="flex w-full items-start gap-2 p-3">
        <button
          type="button"
          onClick={togglePlay}
          className={cn(
            'flex size-9 shrink-0 items-center justify-center rounded-full border font-mono text-[0.65rem] font-bold transition',
            'border-indigo-500/70 bg-indigo-500/10 text-indigo-700',
            'dark:border-indigo-300/70 dark:bg-indigo-300/10 dark:text-indigo-100',
            'hover:scale-105 hover:bg-indigo-500/20 active:scale-95'
          )}
          aria-label={isPlaying ? 'Pause meditation' : 'Play meditation'}
        >
          {isLoading ? (
            <span className="animate-pulse">···</span>
          ) : isPlaying ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <rect x="6" y="4" width="4" height="16" rx="1" />
              <rect x="14" y="4" width="4" height="16" rx="1" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5v14l11-7z" />
            </svg>
          )}
        </button>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-foreground truncate text-xs leading-tight font-semibold sm:text-sm">
              Nathaniel
            </span>
            {isPlaying && (
              <span className="shrink-0 rounded-full border border-indigo-500/25 bg-indigo-500/10 px-1.5 py-0.5 text-[0.55rem] font-bold tracking-wide text-indigo-600 uppercase dark:text-indigo-300">
                Playing
              </span>
            )}
          </div>
          <span className="text-muted-foreground block w-full truncate text-[0.65rem] leading-tight">
            Guided Meditation · The Deep Return
          </span>
        </div>
      </div>

      {/* Progress bar — shown when playing or when duration is known */}
      {(isPlaying || currentTime > 0 || duration > 0) && (
        <div className="px-3 pb-3">
          <div
            className="group/seek bg-muted relative h-1.5 w-full cursor-pointer rounded-full"
            onClick={handleSeek}
          >
            <div
              className="absolute inset-y-0 left-0 rounded-full bg-indigo-500 transition-[width] duration-150"
              style={{ width: `${progress}%` }}
            />
            <div
              className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-indigo-500 opacity-0 shadow-sm transition-opacity group-hover/seek:opacity-100"
              style={{ left: `${progress}%` }}
            />
          </div>
          <div className="text-muted-foreground mt-1 flex justify-between text-[0.6rem]">
            <span>{formatTime(currentTime)}</span>
            <span>{formatTime(duration)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
