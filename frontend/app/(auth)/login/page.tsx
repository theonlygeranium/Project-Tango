import { redirect } from 'next/navigation';
import { LoginForm } from '@/components/auth/LoginForm';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { getCurrentUser } from '@/lib/server/backend';

export default async function LoginPage() {
  const user = await getCurrentUser();
  if (user) {
    redirect(user.role === 'admin' ? '/admin' : '/');
  }

  return (
    <main className="relative flex min-h-svh items-center justify-center overflow-hidden px-4 py-16">
      <div className="bg-primary/10 pointer-events-none absolute -top-32 left-1/2 size-[32rem] -translate-x-1/2 rounded-full blur-3xl" />
      <div className="border-border/60 pointer-events-none absolute inset-0 bg-[linear-gradient(to_right,var(--border)_1px,transparent_1px),linear-gradient(to_bottom,var(--border)_1px,transparent_1px)] [mask-image:radial-gradient(circle_at_center,black,transparent_75%)] bg-[size:42px_42px] opacity-20" />
      <Card className="bg-card/90 relative w-full max-w-md shadow-2xl backdrop-blur-xl">
        <CardHeader className="text-center">
          <p className="text-primary font-mono text-xs font-bold tracking-[0.3em] uppercase">
            EdStratum Labs
          </p>
          <CardTitle className="font-mono text-5xl tracking-tight">TANGO</CardTitle>
          <CardDescription>
            Enter the password provided with your account to continue.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <LoginForm />
        </CardContent>
      </Card>
    </main>
  );
}
