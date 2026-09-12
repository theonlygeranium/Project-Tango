import { cache } from 'react';
import { cookies } from 'next/headers';
import type { AuthSessionResponse, CurrentUser, PersonaCatalogResponse } from '@/lib/auth';

const INTERNAL_API_BASE_URL =
  process.env.TANGO_INTERNAL_API_BASE_URL ??
  process.env.BACKEND_INTERNAL_URL ??
  'http://127.0.0.1:8030';

const SESSION_COOKIE_NAMES = [
  '__Host-tango_session',
  'tango_session',
  '__Host-tango_csrf',
  'tango_csrf',
] as const;

const EMPTY_CATALOG: PersonaCatalogResponse = {
  personas: [],
  llm_models: [],
  default_persona_id: null,
};

export function internalApiUrl(path: string) {
  return new URL(path, INTERNAL_API_BASE_URL);
}

function cookieHeaderFromStore(cookieStore: Awaited<ReturnType<typeof cookies>>): string {
  const parts: string[] = [];
  for (const name of SESSION_COOKIE_NAMES) {
    const cookie = cookieStore.get(name);
    if (cookie?.value) {
      parts.push(`${cookie.name}=${cookie.value}`);
    }
  }
  return parts.join('; ');
}

export async function serverBackendFetch(path: string, init: RequestInit = {}) {
  const cookieStore = await cookies();
  const headers = new Headers(init.headers);
  const cookieHeader = cookieHeaderFromStore(cookieStore);
  if (cookieHeader) {
    headers.set('cookie', cookieHeader);
  }
  headers.set('accept', 'application/json');

  try {
    return await fetch(internalApiUrl(path), {
      ...init,
      headers,
      cache: 'no-store',
    });
  } catch {
    return new Response(JSON.stringify({ detail: 'backend unavailable' }), {
      status: 503,
      headers: { 'content-type': 'application/json' },
    });
  }
}

export const getCurrentUser = cache(async (): Promise<CurrentUser | null> => {
  const response = await serverBackendFetch('/api/auth/me');
  if (!response.ok) {
    return null;
  }
  const payload = (await response.json()) as AuthSessionResponse;
  return payload.user ?? null;
});

export const getAuthorizedPersonaCatalog = cache(async (): Promise<PersonaCatalogResponse> => {
  const response = await serverBackendFetch('/api/personas');
  if (!response.ok) {
    return EMPTY_CATALOG;
  }
  return (await response.json()) as PersonaCatalogResponse;
});
