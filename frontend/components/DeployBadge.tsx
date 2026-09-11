'use client';

import { useCallback, useEffect, useState } from 'react';

type DeployInfo = {
  timestamp: string | null;
  note: string | null;
  version: string | null;
};

function formatTimestamp(iso: string | null): string {
  if (!iso) return 'unknown';
  try {
    const date = new Date(iso);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'America/Los_Angeles',
    });
  } catch {
    return iso;
  }
}

export function DeployBadge() {
  const [info, setInfo] = useState<DeployInfo | null>(null);
  const [open, setOpen] = useState(false);

  const fetchDeployInfo = useCallback(async () => {
    try {
      const response = await fetch('/api/deploy-info', { cache: 'no-store' });
      if (response.ok) {
        const data = (await response.json()) as DeployInfo;
        setInfo(data);
      }
    } catch {
      // Silently ignore — this is a non-critical status badge.
    }
  }, []);

  useEffect(() => {
    void fetchDeployInfo();
  }, [fetchDeployInfo]);

  if (!info || !info.timestamp) {
    return null;
  }

  return (
    <div className="fixed bottom-3 left-3 z-[60]">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="text-muted-foreground/60 hover:text-muted-foreground flex items-center gap-1.5 rounded-md px-2.5 py-1 font-mono text-[10px] tracking-wider uppercase transition-colors"
        aria-expanded={open}
      >
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500/70" />
        Deployed {formatTimestamp(info.timestamp)}
      </button>
      {open && info.note && (
        <div className="bg-background/95 text-foreground mt-1 max-w-xs rounded-md border border-border/40 p-3 shadow-lg backdrop-blur-md">
          <p className="text-xs leading-relaxed">{info.note}</p>
          {info.version && (
            <p className="text-muted-foreground mt-1.5 font-mono text-[10px]">
              v{info.version}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
