'use client';

import { LLM_MODEL_OPTIONS, type LlmModelId, type LlmModelSelectionId } from '@/lib/llm-models';
import { type PersonaId, TANGO_PERSONAS } from '@/lib/personas';
import { cn } from '@/lib/utils';

interface PersonaSelectorProps {
  selectedPersonaId: PersonaId;
  selectedLlmModelId: LlmModelSelectionId;
  disabled?: boolean;
  onPersonaChange: (personaId: PersonaId) => void;
}

function resolveModelLabel(
  personaDefaultModel: LlmModelId,
  selectedLlmModelId: LlmModelSelectionId
): string {
  const effectiveModelId =
    !selectedLlmModelId || selectedLlmModelId === 'persona-default'
      ? personaDefaultModel
      : selectedLlmModelId;
  return (
    LLM_MODEL_OPTIONS.find((opt) => opt.id === effectiveModelId)?.shortLabel ?? effectiveModelId
  );
}

export function PersonaSelector({
  selectedPersonaId,
  selectedLlmModelId,
  disabled = false,
  onPersonaChange,
}: PersonaSelectorProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Choose persona"
      className="grid w-full max-w-4xl grid-cols-2 gap-2 sm:grid-cols-4"
    >
      {TANGO_PERSONAS.map((persona) => {
        const selected = persona.id === selectedPersonaId;
        const modelLabel = resolveModelLabel(persona.defaultLlmModel, selectedLlmModelId);
        const isOverride = !!selectedLlmModelId && selectedLlmModelId !== 'persona-default';

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

            {/* Bottom row: model badge + TTS badge */}
            <span className="mt-0.5 flex w-full items-center gap-1.5 pl-10 sm:pl-11">
              <span
                className={cn(
                  'inline-flex items-center rounded-full border px-1.5 py-0.5 text-[0.55rem] leading-tight font-semibold tracking-wide uppercase',
                  isOverride
                    ? 'border-violet-500/30 bg-violet-500/10 text-violet-700 dark:text-violet-300'
                    : 'border-border/60 bg-muted/50 text-muted-foreground'
                )}
              >
                {modelLabel}
              </span>
              {persona.ttsBackend === 'f5-tts' && (
                <span className="inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 text-[0.55rem] font-bold tracking-wide text-amber-700 uppercase dark:text-amber-200">
                  F5-TTS
                </span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
