'use client';

import { type PersonaId, TANGO_PERSONAS } from '@/lib/personas';
import { cn } from '@/lib/utils';

interface PersonaSelectorProps {
  selectedPersonaId: PersonaId;
  disabled?: boolean;
  onPersonaChange: (personaId: PersonaId) => void;
}

export function PersonaSelector({
  selectedPersonaId,
  disabled = false,
  onPersonaChange,
}: PersonaSelectorProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Choose persona"
      className="grid w-full max-w-2xl grid-cols-2 gap-2"
    >
      {TANGO_PERSONAS.map((persona) => {
        const selected = persona.id === selectedPersonaId;

        return (
          <button
            key={persona.id}
            type="button"
            role="radio"
            disabled={disabled}
            aria-checked={selected}
            onClick={() => onPersonaChange(persona.id)}
            className={cn(
              'group bg-background/70 flex min-h-20 items-center gap-2 rounded-lg border p-2 text-left shadow-sm backdrop-blur-md transition sm:gap-3 sm:p-3',
              'hover:border-ring/45 hover:bg-muted/80 focus-visible:ring-ring/60 focus-visible:ring-2 focus-visible:outline-none',
              'disabled:pointer-events-none disabled:opacity-60',
              selected ? 'border-primary/70 bg-primary/10 ring-primary/20 ring-1' : 'border-border'
            )}
          >
            <span
              className={cn(
                'flex size-10 shrink-0 items-center justify-center rounded-full border font-mono text-xs font-bold sm:size-11',
                persona.accentClassName
              )}
            >
              {persona.initials}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2">
                <span className="text-foreground truncate text-xs font-semibold sm:text-sm">
                  {persona.displayName}
                </span>
                {selected && (
                  <span className="text-primary border-primary/25 bg-primary/10 hidden rounded-full border px-2 py-0.5 text-[0.6rem] font-bold uppercase sm:inline">
                    Selected
                  </span>
                )}
              </span>
              <span className="text-muted-foreground mt-1 block text-[0.7rem] leading-4 sm:text-xs sm:leading-5">
                {persona.roleDescription}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
