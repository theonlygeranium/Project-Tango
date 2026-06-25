import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { AccessToken, type AccessTokenOptions, type VideoGrant } from 'livekit-server-sdk';
import { DEFAULT_PERSONA_ID, type PersonaId, getPersona } from '@/lib/personas';

// NOTE: you are expected to define the following environment variables in `.env.local`:
const API_KEY = process.env.LIVEKIT_API_KEY;
const API_SECRET = process.env.LIVEKIT_API_SECRET;
const LIVEKIT_URL = process.env.NEXT_PUBLIC_LIVEKIT_URL ?? process.env.LIVEKIT_URL;

// don't cache the results
export const revalidate = 0;

export type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
  persona: ReturnType<typeof getPersona>;
};

function parsePersonaId(request: NextRequest): PersonaId {
  const persona =
    request.nextUrl.searchParams.get('persona_id') ??
    request.nextUrl.searchParams.get('persona') ??
    DEFAULT_PERSONA_ID;
  return getPersona(persona).id;
}

function maskClientIp(rawIp: string | null) {
  const candidate = rawIp?.split(',')[0]?.trim();
  if (!candidate) {
    return undefined;
  }

  const ipv4Parts = candidate.split('.');
  if (ipv4Parts.length === 4 && ipv4Parts.every((part) => /^\d{1,3}$/.test(part))) {
    return [...ipv4Parts.slice(0, 3), '0'].join('.');
  }

  const ipv6Parts = candidate.split(':');
  if (ipv6Parts.length > 2) {
    return [...ipv6Parts.slice(0, 4), '0', '0', '0', '0'].join(':');
  }

  return undefined;
}

function historyContext(request: NextRequest) {
  const clientIp = maskClientIp(
    request.headers.get('cf-connecting-ip') ??
      request.headers.get('x-forwarded-for') ??
      request.headers.get('x-real-ip')
  );
  const userAgent = request.headers.get('user-agent')?.slice(0, 512);

  return {
    ...(clientIp ? { client_ip: clientIp } : {}),
    ...(userAgent ? { user_agent: userAgent } : {}),
  };
}

export async function GET(request: NextRequest) {
  try {
    if (LIVEKIT_URL === undefined) {
      throw new Error('LIVEKIT_URL is not defined');
    }
    if (API_KEY === undefined) {
      throw new Error('LIVEKIT_API_KEY is not defined');
    }
    if (API_SECRET === undefined) {
      throw new Error('LIVEKIT_API_SECRET is not defined');
    }

    // Generate participant token
    const persona = getPersona(parsePersonaId(request));
    const participantName = 'Project Tango User';
    const participantIdentity = `tango_user_${crypto.randomUUID().slice(0, 8)}`;
    const roomName = `tango_${persona.id}_${crypto.randomUUID().slice(0, 10)}`;
    const participantToken = await createParticipantToken(
      {
        identity: participantIdentity,
        name: participantName,
        metadata: JSON.stringify({
          persona_id: persona.id,
          persona: persona.id,
          display_name: persona.displayName,
          history: historyContext(request),
        }),
        attributes: {
          'tango.persona': persona.id,
          'tango.display_name': persona.displayName,
        },
      },
      roomName
    );

    // Return connection details
    const data: ConnectionDetails = {
      serverUrl: LIVEKIT_URL,
      roomName,
      participantToken: participantToken,
      participantName,
      persona,
    };
    const headers = new Headers({
      'Cache-Control': 'no-store',
    });
    return NextResponse.json(data, { headers });
  } catch (error) {
    if (error instanceof Error) {
      console.error(error);
      return new NextResponse(error.message, { status: 500 });
    }
  }
}

function createParticipantToken(userInfo: AccessTokenOptions, roomName: string) {
  const at = new AccessToken(API_KEY, API_SECRET, {
    ...userInfo,
    ttl: '15m',
  });
  const grant: VideoGrant = {
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canPublishData: true,
    canSubscribe: true,
  };
  at.addGrant(grant);
  return at.toJwt();
}
