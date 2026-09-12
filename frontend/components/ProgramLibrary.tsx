'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { CaretDown, CaretUp, Sparkle } from '@phosphor-icons/react';
import { type TangoPersona, getPersona } from '@/lib/personas';
import { type Program, fetchPrograms, groupProgramsByPersona } from '@/lib/programs';
import { cn } from '@/lib/utils';

interface ProgramLibraryProps {
  personas: TangoPersona[];
  disabled?: boolean;
  onSelectProgram: (program: Program) => void;
}

export function ProgramLibrary({
  personas,
  disabled = false,
  onSelectProgram,
}: ProgramLibraryProps) {
  const [programs, setPrograms] = useState<Program[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let aborted = false;
    setLoading(true);
    setError(null);
    fetchPrograms()
      .then((data) => {
        if (!aborted) {
          setPrograms(Array.isArray(data) ? data : []);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!aborted) {
          setError(err instanceof Error ? err.message : 'Failed to load programs');
          setLoading(false);
        }
      });
    return () => {
      aborted = true;
    };
  }, []);

  const grouped = useMemo(() => groupProgramsByPersona(programs), [programs]);

  const personaMap = useMemo(() => {
    const map = new Map<string, TangoPersona>();
    for (const persona of personas) {
      map.set(persona.id, persona);
    }
    return map;
  }, [personas]);

  const handleSelect = useCallback(
    (program: Program) => {
      if (disabled) return;
      onSelectProgram(program);
    },
    [disabled, onSelectProgram]
  );

  const hasPrograms = programs.length > 0;

  return (
    <div className="pointer-events-auto w-full max-w-4xl">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setExpanded((prev) => !prev)}
        className={cn(
          'border-border bg-background/70 flex w-full items-center justify-between rounded-lg border px-4 py-2.5 text-left shadow-sm backdrop-blur-md transition',
          'hover:border-ring/45 hover:bg-muted/80',
          disabled && 'opacity-60',
          expanded && 'border-primary/40'
        )}
      >
        <span className="flex items-center gap-2">
          <Sparkle size={18} weight="fill" className="text-primary" />
          <span className="text-foreground font-mono text-xs font-bold uppercase">Programs</span>
          {hasPrograms && (
            <span className="bg-primary/15 text-primary rounded-full px-2 py-0.5 text-[0.6rem] font-bold">
              {programs.length}
            </span>
          )}
        </span>
        {expanded ? (
          <CaretUp size={18} weight="bold" className="text-muted-foreground" />
        ) : (
          <CaretDown size={18} weight="bold" className="text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div className="border-border bg-background/60 mt-2 rounded-lg border p-3 shadow-sm backdrop-blur-md">
          {loading && (
            <p className="text-muted-foreground px-2 py-4 text-center text-xs">
              Loading programs&hellip;
            </p>
          )}

          {error && <p className="text-destructive px-2 py-4 text-center text-xs">{error}</p>}

          {!loading && !error && !hasPrograms && (
            <p className="text-muted-foreground px-2 py-4 text-center text-xs leading-relaxed">
              No programs yet. Say &lsquo;Control Mode&rsquo; during a conversation to create one.
            </p>
          )}

          {!loading && !error && hasPrograms && (
            <div className="flex flex-col gap-4">
              {Array.from(grouped.entries()).map(([personaId, personaPrograms]) => {
                const persona = personaMap.get(personaId) ?? getPersona(personaId);
                return (
                  <div key={personaId}>
                    <div className="mb-2 flex items-center gap-2">
                      <span
                        className={cn(
                          'flex size-6 shrink-0 items-center justify-center rounded-full border font-mono text-[0.55rem] font-bold',
                          persona.accentClassName
                        )}
                      >
                        {persona.initials}
                      </span>
                      <span className="text-foreground/70 font-mono text-[0.65rem] font-bold tracking-wide uppercase">
                        {persona.displayName} Programs
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {personaPrograms.map((program) => (
                        <ProgramCard
                          key={program.id}
                          program={program}
                          personaName={persona.displayName}
                          disabled={disabled}
                          onSelect={() => handleSelect(program)}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface ProgramCardProps {
  program: Program;
  personaName: string;
  disabled: boolean;
  onSelect: () => void;
}

function ProgramCard({ program, personaName, disabled, onSelect }: ProgramCardProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        'bg-background/70 group border-border relative flex w-full flex-col rounded-lg border p-3 text-left shadow-sm backdrop-blur-md transition',
        'hover:border-primary/50 hover:bg-primary/5',
        'disabled:pointer-events-none disabled:opacity-60',
        'focus-visible:ring-ring/60 focus-visible:ring-2 focus-visible:outline-none'
      )}
    >
      <span className="text-foreground truncate text-xs leading-tight font-semibold">
        {program.name}
      </span>
      <span className="text-muted-foreground mt-1 line-clamp-2 text-[0.65rem] leading-tight">
        {program.description || 'No description'}
      </span>
      <span className="text-muted-foreground/60 mt-2 truncate text-[0.55rem] font-medium tracking-wide uppercase">
        {personaName}
      </span>
    </button>
  );
}
