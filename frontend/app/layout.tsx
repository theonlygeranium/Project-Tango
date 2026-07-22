import type { Metadata, Viewport } from 'next';
import { Public_Sans } from 'next/font/google';
import localFont from 'next/font/local';
import { headers } from 'next/headers';
import { ApplyThemeScript, ThemeToggle } from '@/components/theme-toggle';
import { Toaster } from '@/components/ui/sonner';
import { getAppConfig } from '@/lib/utils';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? 'http://localhost:3006'),
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
};

const publicSans = Public_Sans({
  variable: '--font-public-sans',
  subsets: ['latin'],
});

const commitMono = localFont({
  src: [
    {
      path: './fonts/CommitMono-400-Regular.otf',
      weight: '400',
      style: 'normal',
    },
    {
      path: './fonts/CommitMono-700-Regular.otf',
      weight: '700',
      style: 'normal',
    },
    {
      path: './fonts/CommitMono-400-Italic.otf',
      weight: '400',
      style: 'italic',
    },
    {
      path: './fonts/CommitMono-700-Italic.otf',
      weight: '700',
      style: 'italic',
    },
  ],
  variable: '--font-commit-mono',
});

interface RootLayoutProps {
  children: React.ReactNode;
}

export default async function RootLayout({ children }: RootLayoutProps) {
  const hdrs = await headers();
  const { accent, accentDark, pageTitle, pageDescription } = await getAppConfig(hdrs);

  const styles = [
    accent ? `:root { --primary: ${accent}; }` : '',
    accentDark ? `.dark { --primary: ${accentDark}; }` : '',
  ]
    .filter(Boolean)
    .join('\n');

  return (
    <html lang="en" suppressHydrationWarning className="scroll-smooth">
      <head>
        {styles && <style>{styles}</style>}
        <title>{pageTitle}</title>
        <meta name="description" content={pageDescription} />
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <meta name="theme-color" content="#070707" media="(prefers-color-scheme: dark)" />
        <meta name="theme-color" content="#f9f9f6" media="(prefers-color-scheme: light)" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="manifest" href="/site.webmanifest" />
        <ApplyThemeScript />
      </head>
      <body
        className={`${publicSans.variable} ${commitMono.variable} overflow-x-hidden antialiased`}
      >
        {children}
        <Toaster />
        <div className="fixed top-3 right-3 z-[80]">
          <ThemeToggle className="shadow-sm backdrop-blur-md" />
        </div>
      </body>
    </html>
  );
}
