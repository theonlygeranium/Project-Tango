'use client';

import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import {
  type AgentState,
  type ReceivedChatMessage,
  useRoomContext,
  useVoiceAssistant,
} from '@livekit/components-react';
import { CaptionOverlay } from '@/components/CaptionOverlay';
import { toastAlert } from '@/components/alert-toast';
import { AgentControlBar } from '@/components/livekit/agent-control-bar/agent-control-bar';
import { ChatEntry } from '@/components/livekit/chat/chat-entry';
import { ChatMessageView } from '@/components/livekit/chat/chat-message-view';
import { MediaTiles } from '@/components/livekit/media-tiles';
import useChatAndTranscription from '@/hooks/useChatAndTranscription';
import { useDebugMode } from '@/hooks/useDebug';
import { type PersonaId, getPersona } from '@/lib/personas';
import type { AppConfig } from '@/lib/types';
import { cn } from '@/lib/utils';

const CAPTIONS_STORAGE_KEY = 'tango_captions_enabled';

function isAgentAvailable(agentState: AgentState) {
  return agentState == 'listening' || agentState == 'thinking' || agentState == 'speaking';
}

function readCaptionsEnabled() {
  if (typeof window === 'undefined') {
    return true;
  }

  try {
    return window.localStorage.getItem(CAPTIONS_STORAGE_KEY) !== 'false';
  } catch {
    return true;
  }
}

interface SessionViewProps {
  appConfig: AppConfig;
  selectedPersonaId: PersonaId;
  disabled: boolean;
  sessionStarted: boolean;
}

export const SessionView = ({
  appConfig,
  selectedPersonaId,
  disabled,
  sessionStarted,
  ref,
}: React.ComponentProps<'div'> & SessionViewProps) => {
  const { state: agentState } = useVoiceAssistant();
  const [chatOpen, setChatOpen] = useState(false);
  const [captionsEnabled, setCaptionsEnabled] = useState(true);
  const [captionsStorageReady, setCaptionsStorageReady] = useState(false);
  const [connectionFailed, setConnectionFailed] = useState(false);
  const { messages, send } = useChatAndTranscription();
  const room = useRoomContext();
  const selectedPersona = getPersona(selectedPersonaId);

  useDebugMode();

  useEffect(() => {
    setCaptionsEnabled(readCaptionsEnabled());
    setCaptionsStorageReady(true);
  }, []);

  useEffect(() => {
    if (captionsStorageReady) {
      try {
        window.localStorage.setItem(CAPTIONS_STORAGE_KEY, String(captionsEnabled));
      } catch {
        // Storage can be unavailable in restricted browser contexts.
      }
    }
  }, [captionsStorageReady, captionsEnabled]);

  async function handleSendMessage(message: string) {
    await send(message);
  }

  useEffect(() => {
    if (sessionStarted) {
      const timeout = setTimeout(() => {
        if (!isAgentAvailable(agentState)) {
          setConnectionFailed(true);
          const reason =
            agentState === 'connecting'
              ? 'Agent did not join the room. '
              : 'Agent connected but did not complete initializing. ';

          toastAlert({
            title: 'Session ended',
            description: (
              <p className="w-full">
                {reason}
                <a
                  target="_blank"
                  rel="noopener noreferrer"
                  href="https://docs.livekit.io/agents/start/voice-ai/"
                  className="whitespace-nowrap underline"
                >
                  See quickstart guide
                </a>
                .
              </p>
            ),
          });
          room.disconnect();
        }
      }, 10_000);

      return () => clearTimeout(timeout);
    } else {
      setConnectionFailed(false);
    }
  }, [agentState, sessionStarted, room]);

  const { supportsChatInput, supportsVideoInput, supportsScreenShare } = appConfig;
  const capabilities = {
    supportsChatInput,
    supportsVideoInput,
    supportsScreenShare,
  };

  return (
    <main
      ref={ref}
      inert={disabled}
      className={
        // prevent page scrollbar
        // when !chatOpen due to 'translate-y-20'
        cn(!chatOpen && 'max-h-svh overflow-hidden')
      }
    >
      <ChatMessageView
        className={cn(
          'mx-auto min-h-svh w-full max-w-2xl px-3 pt-32 pb-40 transition-[opacity,translate] duration-300 ease-out md:px-0 md:pt-36 md:pb-48',
          chatOpen ? 'translate-y-0 opacity-100 delay-200' : 'translate-y-20 opacity-0'
        )}
      >
        <div className="space-y-3 whitespace-pre-wrap">
          <AnimatePresence>
            {messages.map((message: ReceivedChatMessage) => (
              <motion.div
                key={message.id}
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 1, height: 'auto', translateY: 0.001 }}
                transition={{ duration: 0.5, ease: 'easeOut' }}
              >
                <ChatEntry hideName key={message.id} entry={message} />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </ChatMessageView>

      <div className="bg-background mp-12 fixed top-0 right-0 left-0 h-32 md:h-36">
        {/* skrim */}
        <div className="from-background absolute bottom-0 left-0 h-12 w-full translate-y-full bg-gradient-to-b to-transparent" />
      </div>

      <MediaTiles
        chatOpen={chatOpen}
        connectionFailed={connectionFailed}
        sessionStarted={sessionStarted}
      />

      <CaptionOverlay
        enabled={captionsEnabled}
        messages={messages}
        room={room}
        sessionStarted={sessionStarted}
      />

      <div className="bg-background fixed right-0 bottom-0 left-0 z-50 px-3 pt-2 pb-3 md:px-12 md:pb-12">
        <motion.div
          key="control-bar"
          initial={{ opacity: 0, translateY: '100%' }}
          animate={{
            opacity: sessionStarted ? 1 : 0,
            translateY: sessionStarted ? '0%' : '100%',
          }}
          transition={{ duration: 0.3, delay: sessionStarted ? 0.5 : 0, ease: 'easeOut' }}
        >
          <div className="relative z-10 mx-auto w-full max-w-2xl">
            <div
              aria-live="polite"
              className={cn(
                'pointer-events-none absolute inset-x-0 -top-24 flex justify-center transition-opacity duration-300',
                sessionStarted ? 'opacity-100' : 'opacity-0'
              )}
            >
              <span className="rounded-full border border-white/15 bg-black/50 px-3 py-1 font-mono text-[0.65rem] font-bold tracking-wider text-white/70 uppercase backdrop-blur-md">
                Talking with {selectedPersona.displayName}
              </span>
            </div>
            {appConfig.isPreConnectBufferEnabled && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{
                  opacity: sessionStarted && messages.length === 0 ? 1 : 0,
                  transition: {
                    ease: 'easeIn',
                    delay: messages.length > 0 ? 0 : 0.8,
                    duration: messages.length > 0 ? 0.2 : 0.5,
                  },
                }}
                aria-hidden={messages.length > 0}
                className={cn(
                  'absolute inset-x-0 -top-12 text-center',
                  sessionStarted && messages.length === 0 && 'pointer-events-none'
                )}
              >
                <p className="animate-text-shimmer inline-block !bg-clip-text text-sm font-semibold text-transparent">
                  {selectedPersona.displayName} is listening, ask a question
                </p>
              </motion.div>
            )}

            <AgentControlBar
              capabilities={capabilities}
              captionsEnabled={captionsEnabled}
              onChatOpenChange={setChatOpen}
              onCaptionsEnabledChange={setCaptionsEnabled}
              onSendMessage={handleSendMessage}
            />
          </div>
          {/* skrim */}
          <div className="from-background border-background absolute top-0 left-0 h-12 w-full -translate-y-full bg-gradient-to-t to-transparent" />
        </motion.div>
      </div>
    </main>
  );
};
