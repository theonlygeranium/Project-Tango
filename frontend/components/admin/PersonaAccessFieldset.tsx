'use client';

import { Checkbox } from '@/components/ui/checkbox';
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from '@/components/ui/field';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { BackendLlmModel, BackendPersona, PersonaAccessPolicy } from '@/lib/auth';
import type { LlmModelId } from '@/lib/llm-models';

interface PersonaAccessFieldsetProps {
  personas: BackendPersona[];
  models: BackendLlmModel[];
  value: PersonaAccessPolicy[];
  onChange: (value: PersonaAccessPolicy[]) => void;
  disabled?: boolean;
}

export function PersonaAccessFieldset({
  personas,
  models,
  value,
  onChange,
  disabled = false,
}: PersonaAccessFieldsetProps) {
  function setEnabled(persona: BackendPersona, enabled: boolean) {
    if (enabled) {
      onChange([...value, { persona_id: persona.id, llm_model_override: null }]);
      return;
    }
    onChange(value.filter((policy) => policy.persona_id !== persona.id));
  }

  function setModel(personaId: string, selection: string) {
    onChange(
      value.map((policy) =>
        policy.persona_id === personaId
          ? {
              ...policy,
              llm_model_override:
                selection === 'persona-default' ? null : (selection as LlmModelId),
            }
          : policy
      )
    );
  }

  return (
    <FieldSet>
      <FieldLegend>Persona access</FieldLegend>
      <FieldDescription>
        Enable only the voices this account should use. Model overrides stay inside Tango’s
        allowlist.
      </FieldDescription>
      <FieldGroup className="grid gap-3 md:grid-cols-2">
        {personas.map((persona) => {
          const policy = value.find((item) => item.persona_id === persona.id);
          const enabled = Boolean(policy);
          const checkboxId = `persona-${persona.id}`;
          const defaultModelLabel =
            models.find((model) => model.id === persona.llm_model)?.label ?? persona.llm_model;

          return (
            <Field
              key={persona.id}
              data-disabled={disabled}
              className="bg-card/60 rounded-lg border p-3"
            >
              <div className="flex items-start gap-3">
                <Checkbox
                  id={checkboxId}
                  checked={enabled}
                  onCheckedChange={(checked) => setEnabled(persona, checked === true)}
                  disabled={disabled}
                  aria-label={`Allow ${persona.display_name}`}
                />
                <FieldLabel htmlFor={checkboxId} className="min-w-0 flex-1 cursor-pointer">
                  <span className="block truncate font-semibold">{persona.display_name}</span>
                  <span className="text-muted-foreground block truncate text-xs font-normal">
                    {persona.role_description}
                  </span>
                </FieldLabel>
              </div>
              {enabled && (
                <Select
                  value={policy?.llm_model_override ?? 'persona-default'}
                  onValueChange={(selection) => setModel(persona.id, selection)}
                  disabled={disabled}
                >
                  <SelectTrigger
                    className="w-full"
                    aria-label={`${persona.display_name} model policy`}
                  >
                    <SelectValue placeholder="Persona default" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectGroup>
                      <SelectItem value="persona-default">
                        Persona default · {defaultModelLabel}
                      </SelectItem>
                      {models.map((model) => (
                        <SelectItem key={model.id} value={model.id}>
                          {model.label}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              )}
            </Field>
          );
        })}
      </FieldGroup>
    </FieldSet>
  );
}
