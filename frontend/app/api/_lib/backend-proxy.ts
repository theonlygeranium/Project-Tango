import { NextRequest, NextResponse } from 'next/server';
import { internalApiUrl } from '@/lib/server/backend';

const MUTATION_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function publicOrigin(request: NextRequest) {
  return (
    request.headers.get('origin') ??
    process.env.NEXT_PUBLIC_SITE_URL ??
    request.nextUrl.origin
  ).replace(/\/$/, '');
}

function csrfToken(request: NextRequest) {
  return (
    request.cookies.get('__Host-tango_csrf')?.value ?? request.cookies.get('tango_csrf')?.value
  );
}

function upstreamHeaders(request: NextRequest) {
  const headers = new Headers({ Accept: 'application/json' });
  const passthrough = [
    'content-type',
    'cookie',
    'user-agent',
    'cf-connecting-ip',
    'x-forwarded-for',
    'x-real-ip',
  ];
  for (const name of passthrough) {
    const value = request.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }

  if (MUTATION_METHODS.has(request.method)) {
    headers.set('origin', publicOrigin(request));
    const token = request.headers.get('x-csrf-token') ?? csrfToken(request);
    if (token) {
      headers.set('x-csrf-token', token);
    }
  }
  return headers;
}

function copyResponseHeaders(upstream: Response) {
  const headers = new Headers({ 'Cache-Control': 'no-store' });
  for (const name of ['content-type', 'retry-after']) {
    const value = upstream.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }

  const setCookies = upstream.headers.getSetCookie();
  for (const cookie of setCookies) {
    headers.append('set-cookie', cookie);
  }
  return headers;
}

export async function proxyToBackend(request: NextRequest, path: string) {
  const target = internalApiUrl(path);
  target.search = request.nextUrl.search;
  const hasBody = request.method !== 'GET' && request.method !== 'HEAD';

  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers: upstreamHeaders(request),
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: 'no-store',
      redirect: 'manual',
    });
    const body = upstream.status === 204 ? null : await upstream.arrayBuffer();
    return new NextResponse(body, {
      status: upstream.status,
      headers: copyResponseHeaders(upstream),
    });
  } catch (error) {
    console.error(`Backend proxy failed for ${path}`, error);
    return NextResponse.json(
      { detail: 'Project Tango is temporarily unavailable.' },
      { status: 502 }
    );
  }
}
