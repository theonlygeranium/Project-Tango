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
    <div className="pointer-events-none fixed inset-x-3 bottom-36 z-50 flex justify-center md:bottom-44">
      <div className="flex w-full max-w-2xl flex-col items-center gap-2">
        {agentTrack.text && (
          <p className="bg-background/85 text-foreground line-clamp-2 max-w-full rounded-full border px-4 py-2 text-center text-sm font-medium shadow-sm backdrop-blur-md transition-opacity duration-200 md:text-base">
            {agentTrack.text}
          </p>
        )}
        {userTrack.text && (
          <p
            className={cn(
              'bg-muted/85 text-muted-foreground line-clamp-2 max-w-[92%] rounded-full border px-3 py-1.5 text-center text-xs shadow-sm backdrop-blur-md transition-opacity duration-500 md:text-sm',
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
