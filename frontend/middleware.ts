import { NextRequest, NextResponse } from 'next/server';

const SESSION_COOKIES = ['__Host-tango_session', 'tango_session'];

export function middleware(request: NextRequest) {
  const hasSessionCookie = SESSION_COOKIES.some((name) => request.cookies.has(name));
  if (hasSessionCookie) {
    return NextResponse.next();
  }

  const loginUrl = new URL('/login', request.url);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ['/', '/admin/:path*', '/components/:path*'],
};
