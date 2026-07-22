import { NextRequest, NextResponse } from 'next/server';

const SESSION_COOKIES = ['__Host-tango_session', 'tango_session'];

function publicUrl(pathname: string, request: NextRequest) {
  const configuredOrigin = process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, '');
  if (configuredOrigin) {
    return new URL(pathname, configuredOrigin);
  }
  return new URL(pathname, request.nextUrl.origin);
}

export function middleware(request: NextRequest) {
  const hasSessionCookie = SESSION_COOKIES.some((name) => request.cookies.has(name));
  if (hasSessionCookie) {
    return NextResponse.next();
  }

  return NextResponse.redirect(publicUrl('/login', request));
}

export const config = {
  matcher: ['/', '/admin/:path*', '/components/:path*'],
};
