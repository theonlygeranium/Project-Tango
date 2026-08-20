export type LlmModelId =
  | 'local/qwen3-fast'
  | 'writer/palmyra-x5-voice'
  | 'writer/palmyra-x6'
  | 'writer/palmyra-x5'
  | 'writer/claude-sonnet-4-5'
  | 'writer/claude-opus-4'
  | 'groq/llama4-scout';
export type LlmModelSelectionId = 'persona-default' | LlmModelId;

export type LlmModelOption = {
  id: LlmModelSelectionId;
  label: string;
  shortLabel: string;
};

export const DEFAULT_LLM_MODEL_SELECTION_ID: LlmModelSelectionId = 'persona-default';
export const LLM_MODEL_STORAGE_KEY = 'project-tango.llm-model-id';
export const ADMIN_LLM_MODEL_STORAGE_KEY = 'project-tango.admin-llm-model-selections';

export const LLM_MODEL_OPTIONS: LlmModelOption[] = [
  {
    id: DEFAULT_LLM_MODEL_SELECTION_ID,
    label: 'Persona default',
    shortLabel: 'Default',
  },
  {
    id: 'local/qwen3-fast',
    label: 'Schubert Local Qwen3',
    shortLabel: 'Local Qwen3',
  },
  {
    id: 'writer/palmyra-x5-voice',
    label: 'Writer Palmyra X5 Voice',
    shortLabel: 'Palmyra X5 Voice',
  },
  {
    id: 'writer/palmyra-x6',
    label: 'Writer Palmyra X6',
    shortLabel: 'Palmyra X6',
  },
  {
    id: 'writer/palmyra-x5',
    label: 'Writer Palmyra X5',
    shortLabel: 'Palmyra X5',
  },
  {
    id: 'writer/claude-sonnet-4-5',
    label: 'Claude Sonnet 4.5',
    shortLabel: 'Sonnet 4.5',
  },
  {
    id: 'writer/claude-opus-4',
    label: 'Claude Opus 4',
    shortLabel: 'Opus 4',
  },
  {
    id: 'groq/llama4-scout',
    label: 'Groq Llama 4 Scout',
    shortLabel: 'Groq Scout',
  },
];

const LLM_MODEL_SELECTION_IDS = new Set<string>(LLM_MODEL_OPTIONS.map((option) => option.id));

export function isLlmModelSelectionId(
  value: string | null | undefined
): value is LlmModelSelectionId {
  return Boolean(value && LLM_MODEL_SELECTION_IDS.has(value));
}

export function isLlmModelId(value: string | null | undefined): value is LlmModelId {
  return (
    value === 'local/qwen3-fast' ||
    value === 'writer/palmyra-x5-voice' ||
    value === 'writer/palmyra-x6' ||
    value === 'writer/palmyra-x5' ||
    value === 'writer/claude-sonnet-4-5' ||
    value === 'writer/claude-opus-4' ||
    value === 'groq/llama4-scout'
  );
}

export function llmModelRequestValue(selectionId: LlmModelSelectionId): LlmModelId | undefined {
  return isLlmModelId(selectionId) ? selectionId : undefined;
}

export function getLlmModelOption(selectionId: LlmModelSelectionId): LlmModelOption {
  return LLM_MODEL_OPTIONS.find((option) => option.id === selectionId) ?? LLM_MODEL_OPTIONS[0];
}
