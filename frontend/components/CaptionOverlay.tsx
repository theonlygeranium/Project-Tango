'use client';

import { useEffect, useMemo, useState } from 'react';
import { type Room, RoomEvent } from 'livekit-client';
import type { ReceivedChatMessage } from '@livekit/components-react';
import { toastAlert } from '@/components/alert-toast';
import { cn } from '@/lib/utils';

type CaptionTrack = {
  text: string;
  isFinal?: boolean;
  key: string;
};

type TangoCaptionMessage = {
  type?: string;
  text?: string;
};

interface CaptionOverlayProps {
  enabled: boolean;
  messages: ReceivedChatMessage[];
  room: Room;
  sessionStarted: boolean;
}

function lastMessageForRole(messages: ReceivedChatMessage[], local: boolean) {
  return [...messages].reverse().find((message) => Boolean(message.from?.isLocal) === local);
}

function asTrack(message: ReceivedChatMessage | undefined): CaptionTrack {
  return {
    text: message?.message ?? '',
    key: message?.id ?? '',
  };
}

export function CaptionOverlay({ enabled, messages, room, sessionStarted }: CaptionOverlayProps) {
  const [userVisible, setUserVisible] = useState(false);

  useEffect(() => {
    const handleData = (payload: Uint8Array) => {
      let message: TangoCaptionMessage;
      try {
        message = JSON.parse(new TextDecoder().decode(payload));
      } catch {
        return;
      }

      if (message.type === 'llm_fallback') {
        toastAlert({
          kind: 'info',
          title: 'Switched to cloud model for this response.',
          description: message.text ?? 'Local response timed out.',
        });
      }
    };

    room.on(RoomEvent.DataReceived, handleData);
    return () => {
      room.off(RoomEvent.DataReceived, handleData);
    };
  }, [room]);

  const fallbackUser = useMemo(() => asTrack(lastMessageForRole(messages, true)), [messages]);
  const fallbackAgent = useMemo(() => asTrack(lastMessageForRole(messages, false)), [messages]);
  const userTrack = fallbackUser;
  const agentTrack = fallbackAgent;

  useEffect(() => {
    if (!userTrack.text) {
      setUserVisible(false);
      return;
    }

    setUserVisible(true);
    const timeout = window.setTimeout(() => setUserVisible(false), 2_000);
    return () => window.clearTimeout(timeout);
  }, [userTrack.key, userTrack.text]);

  if (!enabled || !sessionStarted || (!agentTrack.text && !userTrack.text)) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed inset-x-3 bottom-[12.5rem] z-[60] flex justify-center md:bottom-[15rem]">
      <div
        role="status"
        aria-live="polite"
        className="bg-background/90 pointer-events-auto flex max-h-[min(30svh,13rem)] w-full max-w-2xl flex-col gap-2 overflow-y-auto overscroll-contain rounded-lg border border-white/10 p-3 text-center shadow-2xl backdrop-blur-md [scrollbar-color:rgba(255,255,255,0.35)_transparent] [scrollbar-width:thin] md:max-h-[min(34svh,15rem)] md:p-4 dark:bg-black/70 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-white/30 [&::-webkit-scrollbar-track]:bg-transparent"
      >
        {agentTrack.text && (
          <p className="text-foreground text-sm leading-6 font-medium break-words whitespace-pre-wrap md:text-base md:leading-7">
            {agentTrack.text}
          </p>
        )}
        {userTrack.text && (
          <p
            className={cn(
              'text-muted-foreground border-border/70 border-t pt-2 text-xs leading-5 font-medium break-words whitespace-pre-wrap transition-opacity duration-500 md:text-sm md:leading-6',
              userVisible ? 'opacity-100' : 'opacity-0'
            )}
          >
            {userTrack.text}
          </p>
        )}
      </div>
    </div>
  );
}
