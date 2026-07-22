'use client';

import { useTransition } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { SignOutIcon, SlidersHorizontalIcon, UserIcon } from '@phosphor-icons/react';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import type { CurrentUser } from '@/lib/auth';
import { userDisplayName, userInitials } from '@/lib/auth';

export function AccountMenu({ user }: { user: CurrentUser }) {
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();

  function logout() {
    startTransition(async () => {
      await fetch('/api/auth/logout', { method: 'POST' });
      router.replace('/login');
      router.refresh();
    });
  }

  if (pathname.startsWith('/admin')) {
    return null;
  }

  return (
    <div className="fixed top-3 left-3 z-[80] md:top-auto md:bottom-4 md:left-4">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="secondary" size="icon" aria-label="Open account menu">
            <Avatar className="size-7">
              <AvatarFallback className="text-[0.65rem] font-bold">
                {userInitials(user)}
              </AvatarFallback>
            </Avatar>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" sideOffset={8} className="w-64">
          <DropdownMenuGroup>
            <DropdownMenuLabel className="flex flex-col gap-0.5">
              <span>{userDisplayName(user)}</span>
              <span className="text-muted-foreground truncate text-xs font-normal">
                {user.email}
              </span>
            </DropdownMenuLabel>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem asChild>
              <Link href="/">
                <UserIcon />
                Tango
              </Link>
            </DropdownMenuItem>
            {user.role === 'admin' && (
              <DropdownMenuItem asChild>
                <Link href="/admin">
                  <SlidersHorizontalIcon />
                  Administration
                </Link>
              </DropdownMenuItem>
            )}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem onSelect={logout} disabled={isPending}>
              <SignOutIcon />
              {isPending ? 'Signing out…' : 'Sign out'}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
