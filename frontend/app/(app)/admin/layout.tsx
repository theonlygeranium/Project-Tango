import { redirect } from 'next/navigation';
import { AdminShell } from '@/components/admin/AdminShell';
import { getCurrentUser } from '@/lib/server/backend';

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();
  if (!user) {
    redirect('/login');
  }
  if (user.role !== 'admin') {
    redirect('/');
  }

  return <AdminShell user={user}>{children}</AdminShell>;
}
