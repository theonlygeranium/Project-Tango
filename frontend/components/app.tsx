'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ConnectionError,
  ConnectionErrorReason,
  type DisconnectReason,
  Room,
  RoomEvent,
} from 'livekit-client';
import { motion } from 'motion/react';
import { RoomAudioRenderer, RoomContext, StartAudio } from '@livekit/components-react';
import { HistoryPanel } from '@/components/HistoryPanel';
import { toastAlert } from '@/components/alert-toast';
import { SessionView } from '@/components/session-view';
import { Welcome } from '@/components/welcome';
import useConnectionDetails from '@/hooks/useConnectionDetails';
import type { BackendLlmModel } from '@/lib/auth';
import { MAX_RECONNECT_ATTEMPTS, shouldAutoReconnect } from '@/lib/disconnect';
import {
  ADMIN_LLM_MODEL_STORAGE_KEY,
  DEFAULT_LLM_MODEL_SELECTION_ID,
  type LlmModelSelectionId,
  isLlmModelSelectionId,
  llmModelRequestValue,
} from '@/lib/llm-models';
import {
  PERSONA_STORAGE_KEY,
  type PersonaId,
  type TangoPersona,
  isPersonaId,
} from '@/lib/personas';
import type { Program } from '@/lib/programs';
import type { AppConfig } from '@/lib/types';

const MotionWelcome = motion.create(Welcome);
const MotionSessionView = motion.create(SessionView);

function readStoredPersonaId(
  authorizedPersonas: TangoPersona[],
  defaultPersonaId: PersonaId
): PersonaId {
  if (typeof window === 'undefined') {
    return defaultPersonaId;
  }

  try {
    const storedPersonaId = window.localStorage.getItem(PERSONA_STORAGE_KEY);
    return isPersonaId(storedPersonaId) &&
      authorizedPersonas.some((persona) => persona.id === storedPersonaId)
      ? storedPersonaId
      : defaultPersonaId;
  } catch {
    return defaultPersonaId;
  }
}

type AdminModelSelections = Partial<Record<PersonaId, LlmModelSelectionId>>;

function readStoredModelSelections(
  authorizedPersonas: TangoPersona[],
  availableLlmModels: BackendLlmModel[]
): AdminModelSelections {
  if (typeof window === 'undefined') {
    return {};
  }

  try {
    const rawSelections = window.localStorage.getItem(ADMIN_LLM_MODEL_STORAGE_KEY);
    const parsedSelections = rawSelections
      ? (JSON.parse(rawSelections) as Record<string, unknown>)
      : {};
    const allowedModelIds = new Set<string>(availableLlmModels.map((model) => model.id));

    return Object.fromEntries(
      authorizedPersonas.flatMap((persona) => {
        const selection = parsedSelections[persona.id];
        return typeof selection === 'string' &&
          isLlmModelSelectionId(selection) &&
          (selection === DEFAULT_LLM_MODEL_SELECTION_ID || allowedModelIds.has(selection))
          ? [[persona.id, selection]]
          : [];
      })
    );
  } catch {
    return {};
  }
}

interface AppProps {
  appConfig: AppConfig;
  authorizedPersonas: TangoPersona[];
  defaultPersonaId: PersonaId;
  isAdmin: boolean;
  availableLlmModels: BackendLlmModel[];
}

export function App({
  appConfig,
  authorizedPersonas,
  defaultPersonaId,
  isAdmin,
  availableLlmModels,
}: AppProps) {
  const room = useMemo(() => new Room(), []);
  const reconnectAttempts = useRef(0);
  // True while room.connect() is in flight. A failed connect also emits
  // RoomEvent.Disconnected; the connect error path owns that retry.
  const connectInFlight = useRef(false);
  // True between scheduling a retry and starting the next connect. Fetching a
  // fresh token re-runs the connect effect, whose cleanup calls
  // room.disconnect() (reported as CLIENT_INITIATED); that is our own
  // teardown, not a hang-up.
  const tearingDownForRetry = useRef(false);
  const [sessionStarted, setSessionStarted] = useState(false);
  const [canPlayAudio, setCanPlayAudio] = useState(room.canPlaybackAudio);
  const [selectedPersonaId, setSelectedPersonaId] = useState<PersonaId>(defaultPersonaId);
  const [selectedProgram, setSelectedProgram] = useState<Program | null>(null);
  const [selectedModels, setSelectedModels] = useState<AdminModelSelections>({});
  const [preferencesReady, setPreferencesReady] = useState(false);
  const selectedModelId = selectedModels[selectedPersonaId] ?? DEFAULT_LLM_MODEL_SELECTION_ID;
  const onConnectionDetailsError = useCallback((error: Error) => {
    // Without a token there is nothing to connect or retry; leave the
    // "connecting" state instead of hanging.
    reconnectAttempts.current = 0;
    tearingDownForRetry.current = false;
    setSessionStarted(false);
    setSelectedProgram(null);
    toastAlert({
      title: 'Could not start a voice session.',
      description: error.message,
    });
  }, []);
  const { connectionDetails, refreshConnectionDetails, clearConnectionDetails } =
    useConnectionDetails(
      selectedPersonaId,
      preferencesReady && sessionStarted,
      isAdmin ? llmModelRequestValue(selectedModelId) : undefined,
      selectedProgram?.name,
      onConnectionDetailsError
    );

  useEffect(() => {
    setSelectedPersonaId(readStoredPersonaId(authorizedPersonas, defaultPersonaId));
    setSelectedModels(
      isAdmin ? readStoredModelSelections(authorizedPersonas, availableLlmModels) : {}
    );
    setPreferencesReady(true);
  }, [authorizedPersonas, availableLlmModels, defaultPersonaId, isAdmin]);

  useEffect(() => {
    if (preferencesReady) {
      try {
        window.localStorage.setItem(PERSONA_STORAGE_KEY, selectedPersonaId);
      } catch {
        // Storage can be unavailable in restricted browser contexts.
      }
    }
  }, [preferencesReady, selectedPersonaId]);

  useEffect(() => {
    if (preferencesReady && isAdmin) {
      try {
        window.localStorage.setItem(ADMIN_LLM_MODEL_STORAGE_KEY, JSON.stringify(selectedModels));
      } catch {
        // Storage can be unavailable in restricted browser contexts.
      }
    }
  }, [isAdmin, preferencesReady, selectedModels]);

  const endSession = useCallback(() => {
    reconnectAttempts.current = 0;
    tearingDownForRetry.current = false;
    setSessionStarted(false);
    setCanPlayAudio(room.canPlaybackAudio);
    setSelectedProgram(null);
    clearConnectionDetails();
  }, [room, clearConnectionDetails]);

  // Retry with a fresh token (new room grant) up to MAX_RECONNECT_ATTEMPTS,
  // then end the session. Used for unexpected disconnects and for connect or
  // dispatch failures.
  const retryOrEndSession = useCallback(
    (title: string, detail?: string) => {
      if (reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttempts.current += 1;
        tearingDownForRetry.current = true;
        toastAlert({
          title: `${title} Reconnecting...`,
          description: `Attempt ${reconnectAttempts.current} of ${MAX_RECONNECT_ATTEMPTS}${
            detail ? `: ${detail}` : ''
          }`,
        });
        // Finish leaving the old room before fetching a new token: the connect
        // effect only connects when room.state is 'disconnected'.
        void room.disconnect().finally(refreshConnectionDetails);
        return;
      }
      endSession();
      toastAlert({
        title: 'Connection lost.',
        description: 'Please tap Start to reconnect.',
      });
    },
    [room, endSession, refreshConnectionDetails]
  );

  useEffect(() => {
    const onDisconnected = (reason?: DisconnectReason) => {
      if (connectInFlight.current) {
        return; // the connect error path handles this attempt
      }
      if (tearingDownForRetry.current) {
        return; // our own teardown before reconnecting with a fresh token
      }
      if (!shouldAutoReconnect(reason)) {
        endSession();
        return;
      }
      retryOrEndSession('Connection interrupted.');
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
  }, [room, endSession, retryOrEndSession]);

  useEffect(() => {
    let aborted = false;
    if (sessionStarted && room.state === 'disconnected' && connectionDetails) {
      const connect = async () => {
        tearingDownForRetry.current = false;
        connectInFlight.current = true;
        try {
          await room.connect(connectionDetails.serverUrl, connectionDetails.participantToken);
        } catch (error) {
          if (aborted) {
            return;
          }
          if (
            error instanceof ConnectionError &&
            error.reason === ConnectionErrorReason.Cancelled
          ) {
            // room.disconnect() during connect (hang-up, session timeout).
            endSession();
            return;
          }
          const connectionError = error instanceof Error ? error : new Error(String(error));
          retryOrEndSession(
            'Connection failed.',
            `${connectionError.name}: ${connectionError.message}`
          );
          return;
        } finally {
          connectInFlight.current = false;
        }

        if (aborted) {
          return;
        }

        try {
          const dispatchResponse = await fetch('/api/dispatch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ room_name: connectionDetails.roomName }),
          });
          if (!dispatchResponse.ok) {
            throw new Error(`Dispatch failed with HTTP ${dispatchResponse.status}`);
          }
          reconnectAttempts.current = 0;
        } catch (error) {
          if (aborted) {
            return;
          }
          const dispatchError = error instanceof Error ? error : new Error(String(error));
          retryOrEndSession('Agent dispatch failed.', dispatchError.message);
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
    endSession,
    retryOrEndSession,
  ]);

  const { startButtonText } = appConfig;
  const handlePersonaChange = useCallback((personaId: PersonaId) => {
    setSelectedPersonaId(personaId);
  }, []);
  const handleModelChange = useCallback((personaId: PersonaId, modelId: LlmModelSelectionId) => {
    setSelectedModels((current) => ({ ...current, [personaId]: modelId }));
  }, []);

  const handleSelectProgram = useCallback(
    (program: Program) => {
      setSelectedProgram(program);
      setSelectedPersonaId(program.base_persona_id);
      void room
        .startAudio()
        .catch(() => undefined)
        .finally(() => {
          setCanPlayAudio(room.canPlaybackAudio);
        });
      setSessionStarted(true);
    },
    [room]
  );

  return (
    <>
      <MotionWelcome
        key="welcome"
        startButtonText={startButtonText}
        selectedPersonaId={selectedPersonaId}
        personas={authorizedPersonas}
        isAdmin={isAdmin}
        availableLlmModels={availableLlmModels}
        selectedModels={selectedModels}
        onPersonaChange={handlePersonaChange}
        onModelChange={handleModelChange}
        onStartCall={() => {
          void room
            .startAudio()
            .catch(() => undefined)
            .finally(() => {
              setCanPlayAudio(room.canPlaybackAudio);
            });
          setSessionStarted(true);
        }}
        onSelectProgram={handleSelectProgram}
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
        {sessionStarted && (
          <MotionSessionView
            key="session-view"
            appConfig={appConfig}
            selectedPersonaId={selectedPersonaId}
            disabled={false}
            sessionStarted={sessionStarted}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{
              duration: 0.5,
              ease: 'linear',
              delay: 0.5,
            }}
          />
        )}
      </RoomContext.Provider>

      <HistoryPanel hidden={sessionStarted} />
    </>
  );
}
