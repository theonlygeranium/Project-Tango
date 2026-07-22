import { notFound, redirect } from 'next/navigation';
import { AdminDashboard } from '@/components/admin/AdminDashboard';
import type { AdminUsersResponse, PersonaCatalogResponse } from '@/lib/auth';
import { getCurrentUser, serverBackendFetch } from '@/lib/server/backend';

export const dynamic = 'force-dynamic';

export default async function AdminPage() {
  const user = await getCurrentUser();
  if (!user) redirect('/login');
  if (user.role !== 'admin') notFound();

  const [usersResponse, personasResponse] = await Promise.all([
    serverBackendFetch('/api/admin/users'),
    serverBackendFetch('/api/admin/personas'),
  ]);
  if (!usersResponse.ok || !personasResponse.ok) {
    throw new Error('Could not load the Tango administration dashboard.');
  }

  const [{ users }, catalog] = (await Promise.all([
    usersResponse.json(),
    personasResponse.json(),
  ])) as [AdminUsersResponse, PersonaCatalogResponse];

  return <AdminDashboard initialUsers={users} catalog={catalog} />;
}
