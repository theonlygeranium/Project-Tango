import type { PersonaId } from '@/lib/personas';

export type Program = {
  id: string;
  base_persona_id: PersonaId;
  name: string;
  description: string;
  system_prompt: string;
  active: boolean;
  created_at: string;
  updated_at: string;
};

function asProgramList(data: unknown): Program[] {
  if (Array.isArray(data)) {
    return data as Program[];
  }
  if (
    data &&
    typeof data === 'object' &&
    Array.isArray((data as { programs?: unknown }).programs)
  ) {
    return (data as { programs: Program[] }).programs;
  }
  return [];
}

export async function fetchPrograms(personaId?: string): Promise<Program[]> {
  const params = new URLSearchParams();
  if (personaId) {
    params.set('persona_id', personaId);
  }
  const query = params.toString();
  const url = `/api/programs${query ? `?${query}` : ''}`;

  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Failed to fetch programs: HTTP ${res.status}`);
  }
  return asProgramList(await res.json());
}

export function groupProgramsByPersona(programs: Program[]): Map<PersonaId, Program[]> {
  const grouped = new Map<PersonaId, Program[]>();
  if (!Array.isArray(programs)) {
    return grouped;
  }
  for (const program of programs) {
    const list = grouped.get(program.base_persona_id) ?? [];
    list.push(program);
    grouped.set(program.base_persona_id, list);
  }
  return grouped;
}
