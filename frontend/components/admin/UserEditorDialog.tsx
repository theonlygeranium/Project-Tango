'use client';

import { FormEvent, useEffect, useState, useTransition } from 'react';
import { SpinnerGapIcon } from '@phosphor-icons/react';
import { PersonaAccessFieldset } from '@/components/admin/PersonaAccessFieldset';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import type {
  AdminUser,
  GeneratedPasswordResponse,
  PersonaAccessPolicy,
  PersonaCatalogResponse,
  UserMutationPayload,
} from '@/lib/auth';

interface UserEditorDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  user: AdminUser | null;
  catalog: PersonaCatalogResponse;
  onSaved: (user: AdminUser) => void;
  onGeneratedPassword: (password: string, accountName: string) => void;
}

async function responseMessage(response: Response) {
  const payload = (await response.json().catch(() => ({}))) as { detail?: string };
  return payload.detail ?? `Request failed with HTTP ${response.status}`;
}

export function UserEditorDialog({
  open,
  onOpenChange,
  user,
  catalog,
  onSaved,
  onGeneratedPassword,
}: UserEditorDialogProps) {
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [personaAccess, setPersonaAccess] = useState<PersonaAccessPolicy[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    if (!open) return;
    setFirstName(user?.first_name ?? '');
    setLastName(user?.last_name ?? '');
    setEmail(user?.email ?? '');
    setPersonaAccess(user?.persona_access ?? []);
    setError(null);
  }, [open, user]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (personaAccess.length === 0) {
      setError('Select at least one persona for this account.');
      return;
    }

    const payload: UserMutationPayload = {
      first_name: firstName.trim(),
      last_name: lastName.trim(),
      email: email.trim().toLowerCase(),
      persona_access: personaAccess.map(({ persona_id, llm_model_override }) => ({
        persona_id,
        llm_model_override,
      })),
    };

    startTransition(async () => {
      const response = await fetch(user ? `/api/admin/users/${user.id}` : '/api/admin/users', {
        method: user ? 'PATCH' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        setError(await responseMessage(response));
        return;
      }

      const result = (await response.json()) as GeneratedPasswordResponse & { user: AdminUser };
      onSaved(result.user);
      onOpenChange(false);
      if (result.generated_password) {
        onGeneratedPassword(
          result.generated_password,
          `${result.user.first_name} ${result.user.last_name}`.trim()
        );
      }
    });
  }

  return (
    <Dialog open={open} onOpenChange={isPending ? undefined : onOpenChange}>
      <DialogContent className="max-h-[calc(100svh-2rem)] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{user ? 'Edit account' : 'Create account'}</DialogTitle>
          <DialogDescription>
            {user
              ? 'Update identity and persona policy. Passwords are managed separately.'
              : 'Create a regular account and reveal its generated password once.'}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex flex-col gap-6">
          <FieldGroup className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="first-name">First name</FieldLabel>
              <Input
                id="first-name"
                value={firstName}
                onChange={(event) => setFirstName(event.target.value)}
                autoComplete="given-name"
                maxLength={100}
                required
                disabled={isPending}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="last-name">Last name</FieldLabel>
              <Input
                id="last-name"
                value={lastName}
                onChange={(event) => setLastName(event.target.value)}
                autoComplete="family-name"
                maxLength={100}
                required
                disabled={isPending}
              />
            </Field>
            <Field className="sm:col-span-2">
              <FieldLabel htmlFor="email">Email</FieldLabel>
              <Input
                id="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                maxLength={320}
                required
                disabled={isPending}
              />
            </Field>
          </FieldGroup>
          <PersonaAccessFieldset
            personas={catalog.personas}
            models={catalog.llm_models}
            value={personaAccess}
            onChange={setPersonaAccess}
            disabled={isPending}
          />
          {error && <FieldError>{error}</FieldError>}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isPending}
            >
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={isPending}>
              {isPending && <SpinnerGapIcon data-icon="inline-start" className="animate-spin" />}
              {isPending ? 'Saving…' : user ? 'Save changes' : 'Create account'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
