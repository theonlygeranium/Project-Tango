import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export const revalidate = 0;

const API_BASE_URL =
  process.env.TANGO_INTERNAL_API_BASE_URL ??
  process.env.BACKEND_INTERNAL_URL ??
  'http://127.0.0.1:8030';

type RouteContext = {
  params: Promise<{ session_id: string }>;
};

export async function GET(request: NextRequest, context: RouteContext) {
  const { session_id: sessionId } = await context.params;
  const url = new URL(`/api/history/${encodeURIComponent(sessionId)}`, API_BASE_URL);
  url.search = request.nextUrl.search;

  const response = await fetch(url, { cache: 'no-store' });
  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: {
      'Cache-Control': 'no-store',
      'Content-Type': response.headers.get('content-type') ?? 'application/json',
    },
  });
}
