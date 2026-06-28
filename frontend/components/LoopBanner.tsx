'use client';

import { useOpenLoops } from '@/hooks/useOpenLoops';
import { getPersona } from '@/lib/personas';

export function LoopBanner() {
  const { loops, loading, resolveLoop } = useOpenLoops();

  if (loading || loops.length === 0) {
    return null;
  }

  return (
    <section
      aria-label="Unresolved topics from previous sessions"
      className="pointer-events-auto w-full max-w-2xl rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-left shadow-sm backdrop-blur-sm dark:border-amber-300/35 dark:bg-amber-300/10"
    >
      <p className="mb-2 font-mono text-xs font-bold tracking-[0.18em] text-amber-700 uppercase dark:text-amber-200">
        Picking up where you left off
      </p>
      <div className="flex flex-col gap-2">
        {loops.slice(0, 3).map((loop) => {
          const persona = getPersona(loop.persona);
          return (
            <div key={loop.id} className="flex items-start justify-between gap-3">
              <p className="text-foreground/85 text-sm leading-5">
                <span className="font-semibold">{persona.displayName}:</span> {loop.content}
              </p>
              <button
                type="button"
                onClick={() => {
                  void resolveLoop(loop.id);
                }}
                aria-label={`Dismiss unresolved topic: ${loop.content}`}
                className="text-foreground/45 hover:text-foreground focus-visible:ring-ring/50 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold transition-colors focus-visible:ring-[3px] focus-visible:outline-none"
              >
                X
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
