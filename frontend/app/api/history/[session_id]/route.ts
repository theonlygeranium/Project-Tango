import type { NextRequest } from 'next/server';
import { proxyToBackend } from '@/app/api/_lib/backend-proxy';

export const dynamic = 'force-dynamic';

type RouteContext = { params: Promise<{ session_id: string }> };

export async function GET(request: NextRequest, context: RouteContext) {
  const { session_id: sessionId } = await context.params;
  return proxyToBackend(request, `/api/history/${encodeURIComponent(sessionId)}`);
}
