import { useCallback, useEffect, useState } from 'react';
import type { ConnectionDetails } from '@/app/api/connection-details/route';
import type { LlmModelId } from '@/lib/llm-models';
import { DEFAULT_PERSONA_ID, type PersonaId } from '@/lib/personas';

export default function useConnectionDetails(
  personaId: PersonaId = DEFAULT_PERSONA_ID,
  enabled = true,
  llmModel?: LlmModelId
) {
  // Generate room connection details, including:
  //   - A random Room name
  //   - A random Participant name
  //   - An Access Token to permit the participant to join the room
  //   - The URL of the LiveKit server to connect to
  //
  // In real-world application, you would likely allow the user to specify their
  // own participant name, and possibly to choose from existing rooms to join.

  const [connectionDetails, setConnectionDetails] = useState<ConnectionDetails | null>(null);

  const fetchConnectionDetails = useCallback(() => {
    setConnectionDetails(null);
    fetch('/api/connection-details', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persona_id: personaId, llm_model: llmModel }),
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Connection details failed with HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setConnectionDetails({
          ...data,
          serverUrl: data.serverUrl ?? data.server_url,
          roomName: data.roomName ?? data.room_name,
          participantName: data.participantName ?? data.participant_name,
          participantToken: data.participantToken ?? data.participant_token,
          llmModel: data.llmModel ?? data.llm_model,
        });
      })
      .catch((error) => {
        console.error('Error fetching connection details:', error);
      });
  }, [llmModel, personaId]);

  // Clears the cached connection details without triggering a new fetch.
  // Use this on session end so a persona switch starts with a clean slate.
  const clearConnectionDetails = useCallback(() => {
    setConnectionDetails(null);
  }, []);

  useEffect(() => {
    if (enabled) {
      fetchConnectionDetails();
    }
  }, [fetchConnectionDetails, enabled]);

  return {
    connectionDetails,
    refreshConnectionDetails: fetchConnectionDetails,
    clearConnectionDetails,
  };
}
