'use client';

import { useEffect } from 'react';
import { Button } from '@/components/ui/button';

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('Project Tango primary page error', error);
  }, [error]);

  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="text-2xl font-semibold">Tango hit a snag</h1>
      <p className="text-muted-foreground max-w-md text-sm">
        The voice workspace failed to load. You can retry without signing in again.
      </p>
      <Button variant="primary" onClick={() => reset()}>
        Try again
      </Button>
    </main>
  );
}
