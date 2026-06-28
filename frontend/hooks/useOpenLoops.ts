'use client';

import { useCallback, useEffect, useState } from 'react';
import type { OpenLoop } from '@/lib/types';

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  'https://tango-api.schubert.life';

function openLoopsUrl(persona?: string): string {
  const url = new URL('/api/memory/open-loops', API_BASE_URL);
  if (persona) {
    url.searchParams.set('persona', persona);
  }
  return url.toString();
}

export function useOpenLoops(persona?: string) {
  const [loops, setLoops] = useState<OpenLoop[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);

    fetch(openLoopsUrl(persona), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Open loop request failed with HTTP ${response.status}`);
        }
        return response.json();
      })
      .then((data: { open_loops?: OpenLoop[] }) => {
        setLoops(data.open_loops ?? []);
      })
      .catch((error) => {
        if (error instanceof Error && error.name === 'AbortError') {
          return;
        }
        setLoops([]);
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => {
      controller.abort();
    };
  }, [persona]);

  const resolveLoop = useCallback(async (id: string) => {
    setLoops((currentLoops) => currentLoops.filter((loop) => loop.id !== id));
    await fetch(`${openLoopsUrl()}/${id}/resolve`, { method: 'PATCH' }).catch(() => undefined);
  }, []);

  return { loops, loading, resolveLoop };
}
