import { cache } from 'react';
import { cookies } from 'next/headers';
import type { AuthSessionResponse, CurrentUser, PersonaCatalogResponse } from '@/lib/auth';

const INTERNAL_API_BASE_URL =
  process.env.TANGO_INTERNAL_API_BASE_URL ??
  process.env.BACKEND_INTERNAL_URL ??
  'http://127.0.0.1:8030';

export function internalApiUrl(path: string) {
  return new URL(path, INTERNAL_API_BASE_URL);
}

export async function serverBackendFetch(path: string, init: RequestInit = {}) {
  const cookieStore = await cookies();
  const headers = new Headers(init.headers);
  const cookieHeader = cookieStore.toString();
  if (cookieHeader) {
    headers.set('cookie', cookieHeader);
  }
  headers.set('accept', 'application/json');

  return fetch(internalApiUrl(path), {
    ...init,
    headers,
    cache: 'no-store',
  });
}

export const getCurrentUser = cache(async (): Promise<CurrentUser | null> => {
  const response = await serverBackendFetch('/api/auth/me');
  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Session request failed with HTTP ${response.status}`);
  }
  const payload = (await response.json()) as AuthSessionResponse;
  return payload.user;
});

export const getAuthorizedPersonaCatalog = cache(async (): Promise<PersonaCatalogResponse> => {
  const response = await serverBackendFetch('/api/personas');
  if (!response.ok) {
    throw new Error(`Persona request failed with HTTP ${response.status}`);
  }
  return (await response.json()) as PersonaCatalogResponse;
});
