'use client';

import { useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  DotsThreeIcon,
  KeyIcon,
  LockIcon,
  PencilSimpleIcon,
  PlusIcon,
  ShieldCheckIcon,
  UserCheckIcon,
  UserMinusIcon,
  UsersThreeIcon,
} from '@phosphor-icons/react';
import { GeneratedPasswordDialog } from '@/components/admin/GeneratedPasswordDialog';
import { UserEditorDialog } from '@/components/admin/UserEditorDialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogMedia,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { AdminUser, GeneratedPasswordResponse, PersonaCatalogResponse } from '@/lib/auth';
import { userDisplayName, userInitials } from '@/lib/auth';

type AccountAction = 'reset' | 'deactivate' | 'reactivate';

interface PendingAccountAction {
  type: AccountAction;
  user: AdminUser;
}

function actionCopy(action: PendingAccountAction) {
  if (action.type === 'reset') {
    return {
      title: `Reset ${action.user.first_name}’s password?`,
      description:
        'Their old password and active sessions will stop working immediately. The new password is shown once.',
      confirm: 'Reset password',
    };
  }
  if (action.type === 'deactivate') {
    return {
      title: `Deactivate ${action.user.first_name}’s account?`,
      description:
        'They will be signed out and unable to start new Tango sessions until you reactivate the account.',
      confirm: 'Deactivate',
    };
  }
  return {
    title: `Reactivate ${action.user.first_name}’s account?`,
    description: 'Their existing password and persona policy will become active again.',
    confirm: 'Reactivate',
  };
}

function formatDate(value?: string | null) {
  if (!value) return 'Never';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unknown';
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date);
}

export function AdminDashboard({
  initialUsers,
  catalog,
}: {
  initialUsers: AdminUser[];
  catalog: PersonaCatalogResponse;
}) {
  const [users, setUsers] = useState(initialUsers);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAccountAction | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [generated, setGenerated] = useState({ password: '', accountName: '' });

  const sortedUsers = useMemo(
    () =>
      [...users].sort((left, right) => {
        if (left.role !== right.role) return left.role === 'admin' ? -1 : 1;
        return userDisplayName(left).localeCompare(userDisplayName(right));
      }),
    [users]
  );
  const regularUsers = users.filter((user) => user.role === 'regular');
  const activeUsers = regularUsers.filter((user) => user.is_active);
  const personaAssignments = regularUsers.reduce(
    (total, user) => total + user.persona_access.length,
    0
  );

  function replaceUser(updated: AdminUser) {
    setUsers((current) => {
      const exists = current.some((user) => user.id === updated.id);
      return exists
        ? current.map((user) => (user.id === updated.id ? updated : user))
        : [...current, updated];
    });
  }

  function showGeneratedPassword(password: string, accountName: string) {
    setGenerated({ password, accountName });
  }

  async function runAccountAction() {
    if (!pendingAction) return;
    setActionPending(true);
    const { type, user } = pendingAction;
    try {
      const response = await fetch(
        `/api/admin/users/${user.id}/${type === 'reset' ? 'reset-password' : type}`,
        {
          method: 'POST',
        }
      );
      const payload = (await response.json().catch(() => ({}))) as GeneratedPasswordResponse & {
        detail?: string;
        is_active?: boolean;
      };
      if (!response.ok) {
        throw new Error(payload.detail ?? `Request failed with HTTP ${response.status}`);
      }

      if (type === 'reset' && payload.generated_password) {
        showGeneratedPassword(payload.generated_password, userDisplayName(user));
        toast.success('Password reset.');
      } else {
        const isActive = payload.is_active ?? type === 'reactivate';
        replaceUser({ ...user, is_active: isActive });
        toast.success(isActive ? 'Account reactivated.' : 'Account deactivated.');
      }
      setPendingAction(null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Account action failed.');
    } finally {
      setActionPending(false);
    }
  }

  const confirmation = pendingAction ? actionCopy(pendingAction) : null;

  return (
    <main className="flex flex-1 flex-col gap-6 p-4 md:p-6 lg:p-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-primary font-mono text-xs font-bold tracking-wider uppercase">
            Secure access
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">Accounts</h1>
          <p className="text-muted-foreground mt-1 max-w-2xl text-sm">
            Provision password-only accounts, restrict persona access, and set allowlisted model
            policies.
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => {
            setEditingUser(null);
            setEditorOpen(true);
          }}
        >
          <PlusIcon data-icon="inline-start" />
          New account
        </Button>
      </div>

      <section aria-label="Account overview" className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Regular accounts</CardDescription>
            <CardTitle className="text-3xl">{regularUsers.length}</CardTitle>
          </CardHeader>
          <CardContent className="text-muted-foreground flex items-center gap-2 text-xs">
            <UsersThreeIcon /> {activeUsers.length} active
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Persona assignments</CardDescription>
            <CardTitle className="text-3xl">{personaAssignments}</CardTitle>
          </CardHeader>
          <CardContent className="text-muted-foreground flex items-center gap-2 text-xs">
            <ShieldCheckIcon /> Server enforced
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Available personas</CardDescription>
            <CardTitle className="text-3xl">{catalog.personas.length}</CardTitle>
          </CardHeader>
          <CardContent className="text-muted-foreground flex items-center gap-2 text-xs">
            <LockIcon /> Allowlisted models only
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Managed accounts</CardTitle>
          <CardDescription>
            Passwords cannot be recovered. Resetting produces a replacement shown once.
          </CardDescription>
        </CardHeader>
        <CardContent className="px-0">
          {sortedUsers.length === 0 ? (
            <Empty>
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <UsersThreeIcon />
                </EmptyMedia>
                <EmptyTitle>No accounts yet</EmptyTitle>
                <EmptyDescription>Create the first regular Tango account.</EmptyDescription>
              </EmptyHeader>
              <EmptyContent>
                <Button
                  onClick={() => {
                    setEditingUser(null);
                    setEditorOpen(true);
                  }}
                >
                  Create account
                </Button>
              </EmptyContent>
            </Empty>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Account</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="hidden md:table-cell">Personas</TableHead>
                  <TableHead className="hidden lg:table-cell">Last sign-in</TableHead>
                  <TableHead className="w-12">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedUsers.map((user) => (
                  <TableRow key={user.id} className={!user.is_active ? 'opacity-60' : undefined}>
                    <TableCell>
                      <div className="flex min-w-0 items-center gap-3">
                        <Avatar className="size-9">
                          <AvatarFallback className="text-xs font-bold">
                            {userInitials(user)}
                          </AvatarFallback>
                        </Avatar>
                        <div className="min-w-0">
                          <p className="truncate font-medium">{userDisplayName(user)}</p>
                          <p className="text-muted-foreground truncate text-xs">{user.email}</p>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1.5">
                        <Badge variant={user.role === 'admin' ? 'default' : 'secondary'}>
                          {user.role}
                        </Badge>
                        {!user.is_active && <Badge variant="outline">Inactive</Badge>}
                      </div>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <span className="text-muted-foreground text-sm">
                        {user.role === 'admin' ? 'All' : user.persona_access.length}
                      </span>
                    </TableCell>
                    <TableCell className="text-muted-foreground hidden text-sm lg:table-cell">
                      {formatDate(user.last_login_at)}
                    </TableCell>
                    <TableCell>
                      {user.role === 'regular' && (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label={`Manage ${userDisplayName(user)}`}
                            >
                              <DotsThreeIcon weight="bold" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuGroup>
                              <DropdownMenuItem
                                onSelect={() => {
                                  setEditingUser(user);
                                  setEditorOpen(true);
                                }}
                              >
                                <PencilSimpleIcon /> Edit access
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() => setPendingAction({ type: 'reset', user })}
                              >
                                <KeyIcon /> Reset password
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                variant={user.is_active ? 'destructive' : 'default'}
                                onSelect={() =>
                                  setPendingAction({
                                    type: user.is_active ? 'deactivate' : 'reactivate',
                                    user,
                                  })
                                }
                              >
                                {user.is_active ? <UserMinusIcon /> : <UserCheckIcon />}
                                {user.is_active ? 'Deactivate' : 'Reactivate'}
                              </DropdownMenuItem>
                            </DropdownMenuGroup>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <UserEditorDialog
        open={editorOpen}
        onOpenChange={setEditorOpen}
        user={editingUser}
        catalog={catalog}
        onSaved={replaceUser}
        onGeneratedPassword={showGeneratedPassword}
      />
      <GeneratedPasswordDialog
        open={Boolean(generated.password)}
        password={generated.password}
        accountName={generated.accountName}
        onOpenChange={(open) => {
          if (!open) setGenerated({ password: '', accountName: '' });
        }}
      />
      <AlertDialog
        open={Boolean(pendingAction)}
        onOpenChange={(open) => !open && setPendingAction(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogMedia>
              {pendingAction?.type === 'reset' ? <KeyIcon /> : <UserMinusIcon />}
            </AlertDialogMedia>
            <AlertDialogTitle>{confirmation?.title}</AlertDialogTitle>
            <AlertDialogDescription>{confirmation?.description}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={actionPending}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant={pendingAction?.type === 'deactivate' ? 'destructive' : 'default'}
              onClick={() => void runAccountAction()}
              disabled={actionPending}
            >
              {actionPending ? 'Working…' : confirmation?.confirm}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </main>
  );
}
