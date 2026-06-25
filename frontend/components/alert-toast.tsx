'use client';

import { ReactNode } from 'react';
import { toast as sonnerToast } from 'sonner';
import { InfoIcon, WarningIcon } from '@phosphor-icons/react/dist/ssr';
import { cn } from '@/lib/utils';
import { Alert, AlertDescription, AlertTitle } from './ui/alert';

interface ToastProps {
  id: string | number;
  kind?: 'info' | 'warning';
  title: ReactNode;
  description: ReactNode;
}

export function toastAlert(toast: Omit<ToastProps, 'id'>) {
  return sonnerToast.custom(
    (id) => (
      <AlertToast id={id} kind={toast.kind} title={toast.title} description={toast.description} />
    ),
    { duration: 10_000 }
  );
}

function AlertToast(props: ToastProps) {
  const { title, description, id, kind = 'warning' } = props;
  const Icon = kind === 'info' ? InfoIcon : WarningIcon;

  return (
    <Alert
      onClick={() => sonnerToast.dismiss(id)}
      className={cn(kind === 'info' ? 'bg-bgAccentPrimary' : 'bg-accent')}
    >
      <Icon weight="bold" />
      <AlertTitle>{title}</AlertTitle>
      {description && <AlertDescription>{description}</AlertDescription>}
    </Alert>
  );
}
