'use client';

import { type PersonaId, type TangoPersona } from '@/lib/personas';
import { cn } from '@/lib/utils';

interface PersonaSelectorProps {
  selectedPersonaId: PersonaId;
  personas: TangoPersona[];
  disabled?: boolean;
  onPersonaChange: (personaId: PersonaId) => void;
}

export function PersonaSelector({
  selectedPersonaId,
  personas,
  disabled = false,
  onPersonaChange,
}: PersonaSelectorProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Choose persona"
      className="grid w-full max-w-4xl grid-cols-2 gap-2 sm:grid-cols-4"
    >
      {personas.map((persona) => {
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
              'bg-background/70 group relative flex min-h-[5.5rem] w-full flex-col items-start gap-1.5 rounded-lg border p-3 text-left shadow-sm backdrop-blur-md transition',
              'hover:border-ring/45 hover:bg-muted/80 focus-visible:ring-ring/60 focus-visible:ring-2 focus-visible:outline-none',
              'disabled:pointer-events-none disabled:opacity-60',
              selected ? 'border-primary/70 bg-primary/10 ring-primary/20 ring-1' : 'border-border'
            )}
          >
            {/* Top row: avatar + name + selected badge */}
            <span className="flex w-full items-center gap-2">
              <span
                className={cn(
                  'flex size-8 shrink-0 items-center justify-center rounded-full border font-mono text-[0.65rem] font-bold sm:size-9',
                  persona.accentClassName
                )}
              >
                {persona.initials}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-1.5">
                  <span className="text-foreground truncate text-xs leading-tight font-semibold sm:text-sm">
                    {persona.displayName}
                  </span>
                  {selected && (
                    <span className="text-primary border-primary/25 bg-primary/10 shrink-0 rounded-full border px-1.5 py-0.5 text-[0.55rem] font-bold tracking-wide uppercase">
                      Selected
                    </span>
                  )}
                </span>
              </span>
            </span>

            {/* Role description */}
            <span className="text-muted-foreground w-full truncate pl-10 text-[0.65rem] leading-tight sm:pl-11">
              {persona.roleDescription}
            </span>
          </button>
        );
      })}
    </div>
  );
}
