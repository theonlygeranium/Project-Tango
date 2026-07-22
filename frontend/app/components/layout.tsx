import { redirect } from 'next/navigation';
import { ComponentsClientLayout } from '@/app/components/components-client-layout';
import { isPersonaId } from '@/lib/personas';
import { getAuthorizedPersonaCatalog, getCurrentUser } from '@/lib/server/backend';

export default async function ComponentsLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();
  if (!user) {
    redirect('/login');
  }

  const catalog = await getAuthorizedPersonaCatalog();
  const defaultPersonaId = isPersonaId(catalog.default_persona_id)
    ? catalog.default_persona_id
    : null;

  return (
    <ComponentsClientLayout defaultPersonaId={defaultPersonaId}>{children}</ComponentsClientLayout>
  );
}
