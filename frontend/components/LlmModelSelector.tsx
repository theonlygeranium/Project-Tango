'use client';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  LLM_MODEL_OPTIONS,
  type LlmModelSelectionId,
  isLlmModelSelectionId,
} from '@/lib/llm-models';

interface LlmModelSelectorProps {
  selectedLlmModelId: LlmModelSelectionId;
  disabled?: boolean;
  onLlmModelChange: (llmModelId: LlmModelSelectionId) => void;
}

export function LlmModelSelector({
  selectedLlmModelId,
  disabled = false,
  onLlmModelChange,
}: LlmModelSelectorProps) {
  return (
    <Select
      value={selectedLlmModelId}
      disabled={disabled}
      onValueChange={(value) => {
        if (isLlmModelSelectionId(value)) {
          onLlmModelChange(value);
        }
      }}
    >
      <SelectTrigger
        aria-label="Choose model"
        className="bg-background/70 border-border hover:border-ring/45 hover:bg-muted/80 focus:bg-muted/80 h-11 w-full max-w-sm justify-between rounded-lg border px-3 text-left shadow-sm backdrop-blur-md"
      >
        <SelectValue placeholder="Model" />
      </SelectTrigger>
      <SelectContent>
        {LLM_MODEL_OPTIONS.map((model) => (
          <SelectItem key={model.id} value={model.id}>
            {model.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
