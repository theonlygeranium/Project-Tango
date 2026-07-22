import { headers } from 'next/headers';
import { App } from '@/components/app';
import { isLlmModelId } from '@/lib/llm-models';
import { type TangoPersona, getPersona, isPersonaId } from '@/lib/personas';
import { getAuthorizedPersonaCatalog } from '@/lib/server/backend';
import { getAppConfig } from '@/lib/utils';

export default async function Page() {
  const hdrs = await headers();
  const [appConfig, catalog] = await Promise.all([
    getAppConfig(hdrs),
    getAuthorizedPersonaCatalog(),
  ]);
  const authorizedPersonas = catalog.personas.flatMap<TangoPersona>((entry) => {
    if (!isPersonaId(entry.id)) return [];
    const local = getPersona(entry.id);
    const effectiveModel = entry.effective_llm_model ?? entry.llm_model;
    return [
      {
        ...local,
        label: entry.label,
        displayName: entry.display_name,
        roleDescription: entry.role_description,
        defaultLlmModel: isLlmModelId(effectiveModel) ? effectiveModel : local.defaultLlmModel,
        ttsBackend: entry.tts_backend === 'f5-tts' ? 'f5-tts' : local.ttsBackend,
      },
    ];
  });

  if (authorizedPersonas.length === 0) {
    return (
      <main className="flex min-h-svh items-center justify-center px-6 text-center">
        <div className="max-w-md">
          <h1 className="text-2xl font-semibold">No personas assigned</h1>
          <p className="text-muted-foreground mt-2 text-sm">
            Ask your Tango administrator to enable at least one persona for this account.
          </p>
        </div>
      </main>
    );
  }

  const requestedDefault = isPersonaId(catalog.default_persona_id)
    ? catalog.default_persona_id
    : authorizedPersonas[0].id;
  const defaultPersonaId = authorizedPersonas.some((persona) => persona.id === requestedDefault)
    ? requestedDefault
    : authorizedPersonas[0].id;

  return (
    <App
      appConfig={appConfig}
      authorizedPersonas={authorizedPersonas}
      defaultPersonaId={defaultPersonaId}
    />
  );
}
