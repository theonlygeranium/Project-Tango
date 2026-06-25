'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { CaretLeftIcon, ClockIcon } from '@phosphor-icons/react';
import { Button } from '@/components/ui/button';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet';
import { LLM_MODEL_OPTIONS } from '@/lib/llm-models';
import { getPersona } from '@/lib/personas';
import { cn } from '@/lib/utils';

type HistorySession = {
  id: string;
  persona_id: string;
  persona_name: string;
  started_at: string | null;
  ended_at: string | null;
  duration_secs: number | null;
  livekit_room: string | null;
  llm_model: string | null;
  total_tokens: number | null;
  error_code: string | null;
};

type HistoryTurn = {
  turn_index: number;
  speaker: 'user' | 'agent';
  text: string;
  tokens_used: number;
  latency_ms: number | null;
  recorded_at: string | null;
};

type HistoryListResponse = {
  sessions: HistorySession[];
};

type HistoryDetailResponse = {
  session_id: string;
  turns: HistoryTurn[];
};

interface HistoryPanelProps {
  hidden?: boolean;
}

function apiUrl(path: string) {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, '') ?? '';
  return `${baseUrl}${path}`;
}

function formatSessionTime(value: string | null) {
  if (!value) {
    return 'Unknown time';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return 'Unknown time';
  }

  const datePart = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date);
  const timePart = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  }).format(date);

  return `${datePart} · ${timePart}`;
}

function formatDuration(seconds: number | null) {
  if (seconds === null || seconds < 0) {
    return '-';
  }

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return minutes > 0 ? `${minutes}m ${remainingSeconds}s` : `${remainingSeconds}s`;
}

function formatModel(modelId: string | null) {
  if (!modelId) {
    return 'Unknown model';
  }

  return LLM_MODEL_OPTIONS.find((option) => option.id === modelId)?.shortLabel ?? modelId;
}

export function HistoryPanel({ hidden = false }: HistoryPanelProps) {
  const [open, setOpen] = useState(false);
  const [sessions, setSessions] = useState<HistorySession[]>([]);
  const [selectedSession, setSelectedSession] = useState<HistorySession | null>(null);
  const [turns, setTurns] = useState<HistoryTurn[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadingTurns, setLoadingTurns] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedPersona = useMemo(
    () => getPersona(selectedSession?.persona_id),
    [selectedSession?.persona_id]
  );

  const loadSessions = useCallback(async () => {
    setLoadingSessions(true);
    setError(null);
    try {
      const response = await fetch(apiUrl('/api/history'), { cache: 'no-store' });
      if (!response.ok) {
        throw new Error(`History request failed with ${response.status}`);
      }

      const data = (await response.json()) as HistoryListResponse;
      setSessions(data.sessions ?? []);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load history.');
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  const loadTurns = useCallback(async (session: HistorySession) => {
    setSelectedSession(session);
    setLoadingTurns(true);
    setError(null);
    try {
      const response = await fetch(apiUrl(`/api/history/${session.id}`), { cache: 'no-store' });
      if (!response.ok) {
        throw new Error(`Transcript request failed with ${response.status}`);
      }

      const data = (await response.json()) as HistoryDetailResponse;
      setTurns(data.turns ?? []);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load transcript.');
      setTurns([]);
    } finally {
      setLoadingTurns(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      void loadSessions();
    } else {
      setSelectedSession(null);
      setTurns([]);
      setError(null);
    }
  }, [loadSessions, open]);

  if (hidden) {
    return null;
  }

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          variant="secondary"
          size="icon"
          aria-label="Open conversation history"
          title="History"
          className="fixed right-4 bottom-4 z-[60] min-h-11 min-w-11 shadow-lg md:right-12 md:bottom-12"
        >
          <ClockIcon weight="bold" />
        </Button>
      </SheetTrigger>
      <SheetContent className="w-full gap-0 p-0 sm:max-w-md">
        <SheetHeader className="border-border border-b px-5 py-4">
          <div className="flex items-center gap-2">
            {selectedSession && (
              <Button
                variant="ghost"
                size="icon"
                aria-label="Back to sessions"
                onClick={() => {
                  setSelectedSession(null);
                  setTurns([]);
                  setError(null);
                }}
                className="size-9"
              >
                <CaretLeftIcon weight="bold" />
              </Button>
            )}
            <div className="min-w-0">
              <SheetTitle className="font-mono text-sm tracking-wider uppercase">
                {selectedSession ? selectedSession.persona_name : 'Conversation History'}
              </SheetTitle>
              <SheetDescription className="sr-only">
                Read-only Project Tango conversation history.
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          {error && (
            <div className="border-bgSerious bg-bgSerious text-fgSerious mb-3 rounded-md border px-3 py-2 text-sm">
              {error}
            </div>
          )}

          {!selectedSession && (
            <div className="flex flex-col gap-2">
              {loadingSessions && <p className="text-muted-foreground px-1 text-sm">Loading...</p>}
              {!loadingSessions && sessions.length === 0 && (
                <div className="border-border bg-muted/40 rounded-md border px-4 py-8 text-center">
                  <p className="text-sm font-medium">No sessions yet. Start talking!</p>
                </div>
              )}
              {sessions.map((session) => {
                const persona = getPersona(session.persona_id);
                return (
                  <button
                    key={session.id}
                    type="button"
                    onClick={() => void loadTurns(session)}
                    className="border-border hover:bg-muted/60 focus-visible:ring-ring/50 bg-background flex w-full items-center gap-3 rounded-md border p-3 text-left transition-colors focus-visible:ring-[3px] focus-visible:outline-none"
                  >
                    <span
                      className={cn(
                        'flex size-10 shrink-0 items-center justify-center rounded-full border font-mono text-xs font-bold',
                        persona.accentClassName
                      )}
                    >
                      {persona.initials}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold">
                        {session.persona_name}
                      </span>
                      <span className="text-muted-foreground block truncate text-xs">
                        {formatSessionTime(session.started_at)}
                      </span>
                      <span className="text-muted-foreground block truncate font-mono text-[0.65rem] uppercase">
                        {formatModel(session.llm_model)}
                      </span>
                    </span>
                    <span className="text-muted-foreground shrink-0 text-right font-mono text-[0.68rem] uppercase">
                      <span className="block">{formatDuration(session.duration_secs)}</span>
                      <span className="block">{session.total_tokens ?? 0} tok</span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {selectedSession && (
            <div className="flex flex-col gap-3">
              <div className="border-border bg-muted/40 rounded-md border px-3 py-3">
                <div className="flex items-center gap-3">
                  <span
                    className={cn(
                      'flex size-10 shrink-0 items-center justify-center rounded-full border font-mono text-xs font-bold',
                      selectedPersona.accentClassName
                    )}
                  >
                    {selectedPersona.initials}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{selectedSession.persona_name}</p>
                    <p className="text-muted-foreground truncate text-xs">
                      {formatSessionTime(selectedSession.started_at)}
                    </p>
                    <p className="text-muted-foreground truncate font-mono text-[0.65rem] uppercase">
                      {formatModel(selectedSession.llm_model)}
                    </p>
                  </div>
                </div>
              </div>

              {loadingTurns && <p className="text-muted-foreground px-1 text-sm">Loading...</p>}
              {!loadingTurns && turns.length === 0 && (
                <p className="text-muted-foreground px-1 text-sm">No transcript turns recorded.</p>
              )}
              {turns.map((turn) => (
                <div
                  key={`${selectedSession.id}-${turn.turn_index}`}
                  className={cn('flex', turn.speaker === 'user' ? 'justify-end' : 'justify-start')}
                >
                  <div
                    className={cn(
                      'max-w-[85%] rounded-md px-3 py-2 text-sm leading-relaxed',
                      turn.speaker === 'user'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted text-foreground'
                    )}
                  >
                    <p className="whitespace-pre-wrap">{turn.text}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
