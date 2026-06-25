'use client';

import { useEffect, useMemo, useState } from 'react';
import { Room, RoomEvent } from 'livekit-client';
import { motion } from 'motion/react';
import { RoomAudioRenderer, RoomContext, StartAudio } from '@livekit/components-react';
import { HistoryPanel } from '@/components/HistoryPanel';
import { toastAlert } from '@/components/alert-toast';
import { SessionView } from '@/components/session-view';
import { Toaster } from '@/components/ui/sonner';
import { Welcome } from '@/components/welcome';
import useConnectionDetails from '@/hooks/useConnectionDetails';
import {
  DEFAULT_PERSONA_ID,
  PERSONA_STORAGE_KEY,
  type PersonaId,
  isPersonaId,
} from '@/lib/personas';
import type { AppConfig } from '@/lib/types';

const MotionWelcome = motion.create(Welcome);
const MotionSessionView = motion.create(SessionView);

function readStoredPersonaId(): PersonaId {
  if (typeof window === 'undefined') {
    return DEFAULT_PERSONA_ID;
  }

  try {
    const storedPersonaId = window.localStorage.getItem(PERSONA_STORAGE_KEY);
    return isPersonaId(storedPersonaId) ? storedPersonaId : DEFAULT_PERSONA_ID;
  } catch {
    return DEFAULT_PERSONA_ID;
  }
}

interface AppProps {
  appConfig: AppConfig;
}

export function App({ appConfig }: AppProps) {
  const room = useMemo(() => new Room(), []);
  const [sessionStarted, setSessionStarted] = useState(false);
  const [canPlayAudio, setCanPlayAudio] = useState(room.canPlaybackAudio);
  const [selectedPersonaId, setSelectedPersonaId] = useState<PersonaId>(DEFAULT_PERSONA_ID);
  const [personaStorageReady, setPersonaStorageReady] = useState(false);
  const { connectionDetails, refreshConnectionDetails } = useConnectionDetails(
    selectedPersonaId,
    personaStorageReady
  );

  useEffect(() => {
    setSelectedPersonaId(readStoredPersonaId());
    setPersonaStorageReady(true);
  }, []);

  useEffect(() => {
    if (personaStorageReady) {
      try {
        window.localStorage.setItem(PERSONA_STORAGE_KEY, selectedPersonaId);
      } catch {
        // Storage can be unavailable in restricted browser contexts.
      }
    }
  }, [personaStorageReady, selectedPersonaId]);

  useEffect(() => {
    const onDisconnected = () => {
      setSessionStarted(false);
      setCanPlayAudio(room.canPlaybackAudio);
      refreshConnectionDetails();
    };
    const onAudioPlaybackStatusChanged = () => {
      setCanPlayAudio(room.canPlaybackAudio);
    };
    const onMediaDevicesError = (error: Error) => {
      const isPermissionDenied =
        error.name === 'NotAllowedError' || error.name === 'PermissionDeniedError';
      toastAlert({
        title: isPermissionDenied
          ? 'Microphone access is required. Check your browser settings.'
          : 'Encountered an error with your media devices',
        description: isPermissionDenied ? error.message : `${error.name}: ${error.message}`,
      });
    };
    room.on(RoomEvent.MediaDevicesError, onMediaDevicesError);
    room.on(RoomEvent.Disconnected, onDisconnected);
    room.on(RoomEvent.AudioPlaybackStatusChanged, onAudioPlaybackStatusChanged);
    return () => {
      room.off(RoomEvent.Disconnected, onDisconnected);
      room.off(RoomEvent.MediaDevicesError, onMediaDevicesError);
      room.off(RoomEvent.AudioPlaybackStatusChanged, onAudioPlaybackStatusChanged);
    };
  }, [room, refreshConnectionDetails]);

  useEffect(() => {
    let aborted = false;
    if (sessionStarted && room.state === 'disconnected' && connectionDetails) {
      const connect = async () => {
        try {
          await room.connect(connectionDetails.serverUrl, connectionDetails.participantToken);
        } catch (error) {
          if (aborted) {
            return;
          }

          const connectionError = error instanceof Error ? error : new Error(String(error));
          toastAlert({
            title: 'Connection failed. Retrying...',
            description: `${connectionError.name}: ${connectionError.message}`,
          });
          refreshConnectionDetails();
          setSessionStarted(false);
          return;
        }

        if (aborted) {
          return;
        }

        try {
          const apiBase = 'https://tango-api.schubert.life';
          const dispatchResponse = await fetch(apiBase + '/api/dispatch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ room_name: connectionDetails.roomName }),
          });
          if (!dispatchResponse.ok) {
            throw new Error(`Dispatch failed with HTTP ${dispatchResponse.status}`);
          }
        } catch (error) {
          if (aborted) {
            return;
          }

          const dispatchError = error instanceof Error ? error : new Error(String(error));
          toastAlert({
            title: 'Agent dispatch failed. Retrying...',
            description: dispatchError.message,
          });
          refreshConnectionDetails();
          setSessionStarted(false);
          return;
        }

        try {
          await room.localParticipant.setMicrophoneEnabled(true, undefined, {
            preConnectBuffer: appConfig.isPreConnectBufferEnabled,
          });
        } catch (error) {
          if (aborted) {
            return;
          }

          const mediaError = error instanceof Error ? error : new Error(String(error));
          toastAlert({
            title: 'Microphone access is required. Check your browser settings.',
            description: mediaError.message,
          });
        }
      };

      void connect();
    }
    return () => {
      aborted = true;
      room.disconnect();
    };
  }, [
    room,
    sessionStarted,
    connectionDetails,
    appConfig.isPreConnectBufferEnabled,
    refreshConnectionDetails,
  ]);

  const { startButtonText } = appConfig;

  return (
    <>
      <MotionWelcome
        key="welcome"
        startButtonText={startButtonText}
        selectedPersonaId={selectedPersonaId}
        onPersonaChange={setSelectedPersonaId}
        onStartCall={() => {
          void room
            .startAudio()
            .catch(() => undefined)
            .finally(() => {
              setCanPlayAudio(room.canPlaybackAudio);
            });
          setSessionStarted(true);
        }}
        disabled={sessionStarted}
        initial={{ opacity: 0 }}
        animate={{ opacity: sessionStarted ? 0 : 1 }}
        transition={{ duration: 0.5, ease: 'linear', delay: sessionStarted ? 0 : 0.5 }}
      />

      <RoomContext.Provider value={room}>
        {canPlayAudio && <RoomAudioRenderer />}
        <StartAudio
          label="Start Audio"
          className="border-primary/30 bg-primary text-primary-foreground hover:bg-primary-hover focus-visible:ring-ring/50 fixed top-4 left-1/2 z-[70] min-h-11 -translate-x-1/2 rounded-full border px-5 text-xs font-bold tracking-wider uppercase shadow-lg transition-colors focus-visible:ring-[3px] focus-visible:outline-none"
        />
        {/* --- */}
        <MotionSessionView
          key="session-view"
          appConfig={appConfig}
          selectedPersonaId={selectedPersonaId}
          disabled={!sessionStarted}
          sessionStarted={sessionStarted}
          initial={{ opacity: 0 }}
          animate={{ opacity: sessionStarted ? 1 : 0 }}
          transition={{
            duration: 0.5,
            ease: 'linear',
            delay: sessionStarted ? 0.5 : 0,
          }}
        />
      </RoomContext.Provider>

      <Toaster />
      <HistoryPanel hidden={sessionStarted} />
    </>
  );
}
