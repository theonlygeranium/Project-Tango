import { NextRequest, NextResponse } from 'next/server';
import { internalApiUrl } from '@/lib/server/backend';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const target = internalApiUrl('/api/meditation-audio');

  // Pass through range header for seeking support
  const headers = new Headers();
  const range = request.headers.get('range');
  if (range) {
    headers.set('range', range);
  }

  try {
    const upstream = await fetch(target, { headers });

    // Pass through all audio-relevant headers
    const responseHeaders = new Headers();
    for (const name of [
      'content-type',
      'content-length',
      'content-range',
      'accept-ranges',
      'cache-control',
    ]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }

    // Stream the body directly (no buffering)
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch {
    return new NextResponse(null, { status: 502 });
  }
}
