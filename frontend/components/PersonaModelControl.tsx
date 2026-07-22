'use client';

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
} from '@/components/ui/select';
import type { BackendLlmModel } from '@/lib/auth';
import {
  DEFAULT_LLM_MODEL_SELECTION_ID,
  type LlmModelSelectionId,
  getLlmModelOption,
  isLlmModelSelectionId,
} from '@/lib/llm-models';
import type { TangoPersona } from '@/lib/personas';
import { cn } from '@/lib/utils';

interface PersonaModelControlProps {
  persona: TangoPersona;
  models: BackendLlmModel[];
  selectedModelId: LlmModelSelectionId;
  disabled?: boolean;
  glowDelayMs?: number;
  onModelChange: (modelId: LlmModelSelectionId) => void;
}

export function PersonaModelControl({
  persona,
  models,
  selectedModelId,
  disabled = false,
  glowDelayMs = 0,
  onModelChange,
}: PersonaModelControlProps) {
  const defaultModel = models.find((model) => model.id === persona.defaultLlmModel);
  const selectedModel = models.find((model) => model.id === selectedModelId);
  const defaultLabel = defaultModel?.label ?? persona.defaultLlmModel;
  const defaultShortLabel = getLlmModelOption(persona.defaultLlmModel).shortLabel;
  const routingLabel =
    selectedModelId === DEFAULT_LLM_MODEL_SELECTION_ID
      ? 'Use persona default'
      : `Use ${selectedModel?.label ?? selectedModelId}`;
  const routingShortLabel =
    selectedModelId === DEFAULT_LLM_MODEL_SELECTION_ID
      ? 'Use persona default'
      : `Use ${getLlmModelOption(selectedModelId).shortLabel}`;

  return (
    <div
      className={cn('persona-model-glow', persona.modelGlowClassName)}
      style={{ animationDelay: `${glowDelayMs}ms` }}
    >
      <Select
        value={selectedModelId}
        disabled={disabled}
        onValueChange={(value) => {
          if (isLlmModelSelectionId(value)) {
            onModelChange(value);
          }
        }}
      >
        <SelectTrigger
          size="default"
          aria-label={`${persona.displayName} model. Default is ${defaultLabel}. Current routing is ${routingLabel}.`}
          className="persona-model-trigger h-auto min-h-12 w-full max-w-none rounded-md border px-2.5 py-1.5"
        >
          <span className="min-w-0 flex-1 text-left">
            <span className="persona-model-default block truncate text-[0.625rem] leading-4 font-bold tracking-[0.08em] uppercase">
              Default · {defaultShortLabel}
            </span>
            <span className="text-foreground/75 block truncate text-[0.64rem] leading-4 font-medium">
              {routingShortLabel}
            </span>
          </span>
        </SelectTrigger>
        <SelectContent position="popper" className="min-w-[15rem]">
          <SelectGroup>
            <SelectLabel>{persona.displayName} session model</SelectLabel>
            <SelectItem value={DEFAULT_LLM_MODEL_SELECTION_ID}>
              Persona default · {defaultLabel}
            </SelectItem>
            {models.map((model) => (
              <SelectItem key={model.id} value={model.id}>
                {model.label}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>
    </div>
  );
}
