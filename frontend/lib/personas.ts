export type PersonaId = 'therapy' | 'general-info' | 'meditation' | 'pinoy-pride';

export type TangoPersona = {
  id: PersonaId;
  label: string;
  displayName: string;
  roleDescription: string;
  initials: string;
  accentClassName: string;
};

export const DEFAULT_PERSONA_ID: PersonaId = 'therapy';
export const PERSONA_STORAGE_KEY = 'project-tango.persona-id';

export const TANGO_PERSONAS: TangoPersona[] = [
  {
    id: 'therapy',
    label: 'Therapy',
    displayName: 'Damian',
    roleDescription: 'Wellness companion',
    initials: 'DA',
    accentClassName:
      'border-sky-500/70 bg-sky-500/10 text-sky-700 dark:border-sky-300/70 dark:bg-sky-300/10 dark:text-sky-100',
  },
  {
    id: 'general-info',
    label: 'General Info',
    displayName: 'Chris (British)',
    roleDescription: 'General assistant',
    initials: 'CH',
    accentClassName:
      'border-emerald-500/70 bg-emerald-500/10 text-emerald-700 dark:border-emerald-300/70 dark:bg-emerald-300/10 dark:text-emerald-100',
  },
  {
    id: 'meditation',
    label: 'Meditation',
    displayName: 'Nathaniel',
    roleDescription: 'Meditation guide',
    initials: 'NA',
    accentClassName:
      'border-indigo-500/70 bg-indigo-500/10 text-indigo-700 dark:border-indigo-300/70 dark:bg-indigo-300/10 dark:text-indigo-100',
  },
  {
    id: 'pinoy-pride',
    label: 'Pinoy Pride',
    displayName: 'Tita',
    roleDescription: 'Pinoy pride',
    initials: 'TI',
    accentClassName:
      'border-rose-500/70 bg-rose-500/10 text-rose-700 dark:border-rose-300/70 dark:bg-rose-300/10 dark:text-rose-100',
  },
];

export function isPersonaId(value: string | null | undefined): value is PersonaId {
  return TANGO_PERSONAS.some((persona) => persona.id === value);
}

export function getPersona(personaId: string | null | undefined): TangoPersona {
  return TANGO_PERSONAS.find((persona) => persona.id === personaId) ?? TANGO_PERSONAS[0];
}
