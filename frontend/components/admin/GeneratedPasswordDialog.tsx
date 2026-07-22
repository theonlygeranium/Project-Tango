'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { CheckIcon, CopyIcon, KeyIcon } from '@phosphor-icons/react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupInput,
} from '@/components/ui/input-group';

interface GeneratedPasswordDialogProps {
  open: boolean;
  password: string;
  accountName: string;
  onOpenChange: (open: boolean) => void;
}

export function GeneratedPasswordDialog({
  open,
  password,
  accountName,
  onOpenChange,
}: GeneratedPasswordDialogProps) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (open) setCopied(false);
  }, [open, password]);

  async function copyPassword() {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
      toast.success('Password copied.');
    } catch {
      toast.error('Could not copy automatically. Select the password and copy it manually.');
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Save this password now</DialogTitle>
          <DialogDescription>
            This is the new sign-in password for {accountName || 'the account'}.
          </DialogDescription>
        </DialogHeader>
        <Alert>
          <KeyIcon />
          <AlertTitle>Shown once</AlertTitle>
          <AlertDescription>
            Tango does not store recoverable passwords. Closing this dialog permanently removes it
            from the dashboard.
          </AlertDescription>
        </Alert>
        <InputGroup>
          <InputGroupInput
            value={password}
            readOnly
            aria-label={`Generated password for ${accountName}`}
            className="font-mono text-lg tracking-widest"
            onFocus={(event) => event.currentTarget.select()}
          />
          <InputGroupAddon align="inline-end">
            <InputGroupButton
              type="button"
              onClick={copyPassword}
              aria-label="Copy generated password"
            >
              {copied ? <CheckIcon /> : <CopyIcon />}
              {copied ? 'Copied' : 'Copy'}
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
        <DialogFooter>
          <Button type="button" variant="primary" onClick={() => onOpenChange(false)}>
            I saved it
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
