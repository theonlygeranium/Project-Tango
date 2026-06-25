import { useCallback, useEffect, useState } from 'react';
import type { ConnectionDetails } from '@/app/api/connection-details/route';
import { DEFAULT_PERSONA_ID, type PersonaId } from '@/lib/personas';

export default function useConnectionDetails(personaId: PersonaId = DEFAULT_PERSONA_ID, enabled = true) {
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
    const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
    const endpoint =
      process.env.NEXT_PUBLIC_CONN_DETAILS_ENDPOINT ??
      (apiBaseUrl ? `${apiBaseUrl.replace(/\/$/, '')}/api/connection-details` : '/api/connection-details');
    const url = new URL(endpoint, window.location.origin);
    url.searchParams.set('persona_id', personaId);
    fetch(url.toString())
      .then((res) => res.json())
      .then((data) => {
        setConnectionDetails(data);
      })
      .catch((error) => {
        console.error('Error fetching connection details:', error);
      });
  }, [personaId]);

  useEffect(() => {
    if (enabled) { fetchConnectionDetails(); }
  }, [fetchConnectionDetails, enabled]);

  return { connectionDetails, refreshConnectionDetails: fetchConnectionDetails };
}
