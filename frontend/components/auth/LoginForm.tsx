'use client';

import { FormEvent, useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import { EyeIcon, EyeSlashIcon, LockKeyIcon, SpinnerGapIcon } from '@phosphor-icons/react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Field, FieldError, FieldGroup, FieldLabel } from '@/components/ui/field';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from '@/components/ui/input-group';
import type { AuthSessionResponse } from '@/lib/auth';

export function LoginForm() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    startTransition(async () => {
      try {
        const response = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password }),
        });
        const payload = (await response
          .json()
          .catch(() => ({}))) as Partial<AuthSessionResponse> & {
          detail?: string;
        };
        if (!response.ok || !payload.user) {
          setError(
            response.status === 429
              ? (payload.detail ?? 'Too many attempts. Wait a moment and try again.')
              : 'That password was not recognized.'
          );
          return;
        }

        router.replace(payload.user.role === 'admin' ? '/admin' : '/');
        router.refresh();
      } catch {
        setError('Project Tango is temporarily unavailable. Please try again.');
      }
    });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-5">
      {error && (
        <Alert variant="destructive">
          <LockKeyIcon />
          <AlertTitle>Unable to sign in</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <FieldGroup>
        <Field data-invalid={Boolean(error)}>
          <FieldLabel htmlFor="password">Password</FieldLabel>
          <InputGroup>
            <InputGroupInput
              id="password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              autoFocus
              required
              maxLength={128}
              aria-invalid={Boolean(error)}
              placeholder="Enter your Tango password"
            />
            <InputGroupAddon align="inline-end">
              <InputGroupButton
                type="button"
                size="icon-xs"
                onClick={() => setShowPassword((current) => !current)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeSlashIcon /> : <EyeIcon />}
              </InputGroupButton>
            </InputGroupAddon>
          </InputGroup>
          {error && <FieldError>{error}</FieldError>}
        </Field>
      </FieldGroup>
      <Button type="submit" variant="primary" size="lg" disabled={isPending || !password}>
        {isPending && <SpinnerGapIcon data-icon="inline-start" className="animate-spin" />}
        {isPending ? 'Signing in…' : 'Sign in'}
      </Button>
    </form>
  );
}
