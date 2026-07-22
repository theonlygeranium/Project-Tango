import { CpuIcon, WaveformIcon } from '@phosphor-icons/react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { BackendPersona, PersonaCatalogResponse } from '@/lib/auth';
import type { LlmModelId } from '@/lib/llm-models';
import { getPersona, isPersonaId } from '@/lib/personas';
import { cn } from '@/lib/utils';

const MODEL_GLOW_CLASSES: Record<LlmModelId, string> = {
  'local/qwen3-fast': 'persona-model-glow-sky',
  'writer/palmyra-x5-voice': 'persona-model-glow-emerald',
  'groq/llama4-scout': 'persona-model-glow-fuchsia',
};

function initials(displayName: string) {
  return displayName
    .split(/\s+/)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();
}

function modelProvider(modelId: LlmModelId) {
  if (modelId.startsWith('local/')) return 'Schubert · Local GPU';
  if (modelId.startsWith('writer/')) return 'Writer · Hosted';
  return 'Groq · Hosted';
}

function ttsDetails(persona: BackendPersona) {
  return persona.tts_backend === 'f5-tts'
    ? { name: 'F5-TTS', detail: 'Self-hosted voice' }
    : { name: 'ElevenLabs', detail: 'Flash v2.5' };
}

function sttDetails(persona: BackendPersona) {
  return persona.stt_language === 'tl' ? 'Nova-3 · Tagalog' : 'Flux · English';
}

function personaStyle(persona: BackendPersona) {
  if (!isPersonaId(persona.id)) {
    return {
      accentClassName: 'border-primary/50 bg-primary/10 text-primary',
      glowClassName: MODEL_GLOW_CLASSES[persona.llm_model],
      initials: initials(persona.display_name),
    };
  }

  const localPersona = getPersona(persona.id);
  return {
    accentClassName: localPersona.accentClassName,
    glowClassName: localPersona.modelGlowClassName,
    initials: localPersona.initials,
  };
}

function ModelRoute({
  persona,
  modelLabel,
  delay,
}: {
  persona: BackendPersona;
  modelLabel: string;
  delay: number;
}) {
  const { glowClassName } = personaStyle(persona);

  return (
    <div
      className={cn(
        'persona-model-glow persona-route-surface min-w-[12rem] px-3 py-2',
        glowClassName
      )}
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex items-center gap-2">
        <span className="persona-route-beacon" aria-hidden="true" />
        <span className="text-sm leading-5 font-semibold whitespace-normal">{modelLabel}</span>
      </div>
      <code className="text-muted-foreground mt-1 block truncate text-[0.68rem]">
        {persona.llm_model}
      </code>
    </div>
  );
}

export function PersonaModelMap({ catalog }: { catalog: PersonaCatalogResponse }) {
  const modelLabels = new Map(catalog.llm_models.map((model) => [model.id, model.label]));
  const modelCounts = new Map<LlmModelId, number>();
  for (const persona of catalog.personas) {
    modelCounts.set(persona.llm_model, (modelCounts.get(persona.llm_model) ?? 0) + 1);
  }

  return (
    <Card className="overflow-hidden py-0">
      <CardHeader className="border-b py-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>Persona model map</CardTitle>
            <CardDescription className="mt-2 max-w-2xl">
              Current source-controlled defaults and voice pipelines. Account-level overrides remain
              managed per user.
            </CardDescription>
          </div>
          <div className="text-muted-foreground flex gap-5 text-xs sm:text-right">
            <span>
              <strong className="text-foreground block text-lg font-semibold">
                {catalog.personas.length}
              </strong>
              personas
            </span>
            <span>
              <strong className="text-foreground block text-lg font-semibold">
                {catalog.llm_models.length}
              </strong>
              model routes
            </span>
          </div>
        </div>
      </CardHeader>

      <CardContent className="px-0">
        <section aria-label="Allowlisted model routes" className="border-b px-4 py-4 sm:px-6">
          <p className="text-muted-foreground mb-3 font-mono text-[0.68rem] font-bold tracking-wider uppercase">
            Allowlisted models
          </p>
          <div className="grid gap-3 lg:grid-cols-3">
            {catalog.llm_models.map((model, index) => (
              <div
                key={model.id}
                className={cn(
                  'persona-model-glow persona-route-surface flex min-w-0 items-center gap-3 p-4',
                  MODEL_GLOW_CLASSES[model.id]
                )}
                style={{ animationDelay: `${index * -280}ms` }}
              >
                <span className="persona-route-icon" aria-hidden="true">
                  <CpuIcon weight="duotone" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm leading-5 font-semibold">{model.label}</span>
                  <code className="text-muted-foreground mt-0.5 block truncate text-[0.68rem]">
                    {model.id}
                  </code>
                </span>
                <span className="text-muted-foreground shrink-0 text-right text-xs">
                  <strong className="text-foreground block text-base font-semibold">
                    {modelCounts.get(model.id) ?? 0}
                  </strong>
                  defaults
                </span>
              </div>
            ))}
          </div>
        </section>

        <div className="hidden xl:block">
          <Table className="min-w-[960px]">
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-12 pl-6">#</TableHead>
                <TableHead>Persona</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Default LLM</TableHead>
                <TableHead>Provider</TableHead>
                <TableHead className="pr-6">Voice pipeline</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {catalog.personas.map((persona, index) => {
                const style = personaStyle(persona);
                const tts = ttsDetails(persona);

                return (
                  <TableRow
                    key={persona.id}
                    className={cn('admin-persona-route-row', style.glowClassName)}
                  >
                    <TableCell className="text-muted-foreground pl-6 font-mono text-xs">
                      {String(index + 1).padStart(2, '0')}
                    </TableCell>
                    <TableCell>
                      <div className="flex min-w-[11rem] items-center gap-3">
                        <span
                          className={cn(
                            'flex size-9 shrink-0 items-center justify-center rounded-full border font-mono text-[0.65rem] font-bold',
                            style.accentClassName
                          )}
                        >
                          {style.initials}
                        </span>
                        <span className="min-w-0">
                          <span className="block font-semibold">{persona.display_name}</span>
                          <code className="text-muted-foreground block text-[0.68rem]">
                            {persona.id}
                          </code>
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground whitespace-normal">
                      <span className="block max-w-[10rem] leading-5">
                        {persona.role_description}
                      </span>
                    </TableCell>
                    <TableCell>
                      <ModelRoute
                        persona={persona}
                        modelLabel={modelLabels.get(persona.llm_model) ?? persona.llm_model}
                        delay={index * -170}
                      />
                    </TableCell>
                    <TableCell>
                      <span className="text-sm font-medium">
                        {modelProvider(persona.llm_model)}
                      </span>
                    </TableCell>
                    <TableCell className="pr-6">
                      <div className="flex min-w-[11rem] items-center gap-2.5">
                        <WaveformIcon className="text-muted-foreground size-4" weight="duotone" />
                        <span>
                          <span className="block text-sm font-medium">{tts.name}</span>
                          <span className="text-muted-foreground block text-xs">
                            {tts.detail} · {sttDetails(persona)}
                          </span>
                        </span>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>

        <div className="divide-y xl:hidden">
          {catalog.personas.map((persona, index) => {
            const style = personaStyle(persona);
            const tts = ttsDetails(persona);

            return (
              <div key={persona.id} className="p-4">
                <div
                  className={cn(
                    'persona-model-glow persona-route-surface p-4',
                    style.glowClassName
                  )}
                  style={{ animationDelay: `${index * -170}ms` }}
                >
                  <div className="flex items-center gap-3">
                    <span
                      className={cn(
                        'flex size-9 shrink-0 items-center justify-center rounded-full border font-mono text-[0.65rem] font-bold',
                        style.accentClassName
                      )}
                    >
                      {style.initials}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block font-semibold">{persona.display_name}</span>
                      <code className="text-muted-foreground block text-[0.68rem]">
                        {persona.id}
                      </code>
                    </span>
                    <span className="text-muted-foreground font-mono text-xs">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                  </div>

                  <dl className="mt-4 grid gap-3 text-sm">
                    <div className="grid grid-cols-[6.5rem_1fr] gap-3">
                      <dt className="text-muted-foreground">Role</dt>
                      <dd>{persona.role_description}</dd>
                    </div>
                    <div className="grid grid-cols-[6.5rem_1fr] gap-3">
                      <dt className="text-muted-foreground">Default LLM</dt>
                      <dd>
                        <span className="block font-medium">
                          {modelLabels.get(persona.llm_model) ?? persona.llm_model}
                        </span>
                        <code className="text-muted-foreground text-[0.68rem] break-all">
                          {persona.llm_model}
                        </code>
                      </dd>
                    </div>
                    <div className="grid grid-cols-[6.5rem_1fr] gap-3">
                      <dt className="text-muted-foreground">Provider</dt>
                      <dd>{modelProvider(persona.llm_model)}</dd>
                    </div>
                    <div className="grid grid-cols-[6.5rem_1fr] gap-3">
                      <dt className="text-muted-foreground">Voice</dt>
                      <dd>
                        {tts.name} · {tts.detail}
                        <span className="text-muted-foreground block text-xs">
                          {sttDetails(persona)}
                        </span>
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
