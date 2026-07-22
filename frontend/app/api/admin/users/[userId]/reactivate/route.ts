import type { NextRequest } from 'next/server';
import { proxyToBackend } from '@/app/api/_lib/backend-proxy';

type RouteContext = { params: Promise<{ userId: string }> };

export async function POST(request: NextRequest, context: RouteContext) {
  const { userId } = await context.params;
  return proxyToBackend(request, `/api/admin/users/${encodeURIComponent(userId)}/reactivate`);
}
