import type { NextRequest } from 'next/server';
import { proxyToBackend } from '@/app/api/_lib/backend-proxy';

type RouteContext = { params: Promise<{ loop_id: string }> };

export async function PATCH(request: NextRequest, context: RouteContext) {
  const { loop_id: loopId } = await context.params;
  return proxyToBackend(request, `/api/memory/open-loops/${encodeURIComponent(loopId)}/resolve`);
}
