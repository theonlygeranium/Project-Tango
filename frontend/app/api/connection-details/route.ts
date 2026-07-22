import type { NextRequest } from 'next/server';
import { proxyToBackend } from '@/app/api/_lib/backend-proxy';

export type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
  llmModel: string;
  persona: { id: string; displayName?: string; display_name?: string };
};

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  return proxyToBackend(request, '/api/connection-details');
}
