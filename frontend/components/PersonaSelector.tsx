'use client';

import { PersonaModelControl } from '@/components/PersonaModelControl';
import type { BackendLlmModel } from '@/lib/auth';
import { DEFAULT_LLM_MODEL_SELECTION_ID, type LlmModelSelectionId } from '@/lib/llm-models';
import { type PersonaId, type TangoPersona } from '@/lib/personas';
import { cn } from '@/lib/utils';

interface PersonaSelectorProps {
  selectedPersonaId: PersonaId;
  personas: TangoPersona[];
  isAdmin?: boolean;
  availableLlmModels?: BackendLlmModel[];
  selectedModels?: Partial<Record<PersonaId, LlmModelSelectionId>>;
  disabled?: boolean;
  onPersonaChange: (personaId: PersonaId) => void;
  onModelChange?: (personaId: PersonaId, modelId: LlmModelSelectionId) => void;
}

export function PersonaSelector({
  selectedPersonaId,
  personas,
  isAdmin = false,
  availableLlmModels = [],
  selectedModels = {},
  disabled = false,
  onPersonaChange,
  onModelChange,
}: PersonaSelectorProps) {
  return (
    <div
      role="group"
      aria-label="Choose persona"
      className={cn(
        'grid w-full grid-cols-2 gap-2 sm:grid-cols-4',
        isAdmin ? 'max-w-6xl' : 'max-w-4xl'
      )}
    >
      {personas.map((persona, index) => {
        const selected = persona.id === selectedPersonaId;

        return (
          <div
            key={persona.id}
            className={cn(
              'bg-background/70 group relative flex w-full flex-col rounded-lg border text-left shadow-sm backdrop-blur-md transition',
              'hover:border-ring/45 hover:bg-muted/80',
              disabled && 'opacity-60',
              selected ? 'border-primary/70 bg-primary/10 ring-primary/20 ring-1' : 'border-border'
            )}
          >
            <button
              type="button"
              disabled={disabled}
              aria-pressed={selected}
              onClick={() => onPersonaChange(persona.id)}
              className={cn(
                'focus-visible:ring-ring/60 flex w-full flex-1 flex-col items-start gap-1.5 rounded-lg p-3 text-left focus-visible:ring-2 focus-visible:outline-none',
                'disabled:pointer-events-none',
                isAdmin ? 'min-h-[5.25rem] pb-2' : 'min-h-[5.5rem]'
              )}
            >
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

              <span className="text-muted-foreground w-full truncate pl-10 text-[0.65rem] leading-tight sm:pl-11">
                {persona.roleDescription}
              </span>
            </button>

            {isAdmin && onModelChange && (
              <div className="px-2.5 pb-2.5">
                <PersonaModelControl
                  persona={persona}
                  models={availableLlmModels}
                  selectedModelId={selectedModels[persona.id] ?? DEFAULT_LLM_MODEL_SELECTION_ID}
                  disabled={disabled}
                  glowDelayMs={index * -170}
                  onModelChange={(modelId) => onModelChange(persona.id, modelId)}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
