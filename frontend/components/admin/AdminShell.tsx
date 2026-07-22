'use client';

import { ReactNode, useTransition } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { HouseIcon, SignOutIcon, UsersThreeIcon, WaveformIcon } from '@phosphor-icons/react';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarSeparator,
  SidebarTrigger,
} from '@/components/ui/sidebar';
import type { CurrentUser } from '@/lib/auth';
import { userDisplayName, userInitials } from '@/lib/auth';

export function AdminShell({ user, children }: { user: CurrentUser; children: ReactNode }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function logout() {
    startTransition(async () => {
      await fetch('/api/auth/logout', { method: 'POST' });
      router.replace('/login');
      router.refresh();
    });
  }

  return (
    <SidebarProvider>
      <Sidebar variant="inset" collapsible="icon">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" asChild>
                <Link href="/admin">
                  <span className="bg-primary text-primary-foreground flex size-8 items-center justify-center rounded-lg">
                    <WaveformIcon weight="bold" />
                  </span>
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate font-mono font-bold tracking-wider">TANGO</span>
                    <span className="text-muted-foreground truncate text-xs">Administration</span>
                  </span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarSeparator />
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Workspace</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton asChild isActive tooltip="Accounts">
                    <Link href="/admin">
                      <UsersThreeIcon />
                      <span>Accounts</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton asChild tooltip="Open Tango">
                    <Link href="/">
                      <HouseIcon />
                      <span>Open Tango</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" onClick={logout} disabled={isPending} tooltip="Sign out">
                <Avatar className="size-8">
                  <AvatarFallback className="text-xs font-bold">
                    {userInitials(user)}
                  </AvatarFallback>
                </Avatar>
                <span className="flex min-w-0 flex-1 flex-col text-left">
                  <span className="truncate text-sm font-medium">{userDisplayName(user)}</span>
                  <span className="text-muted-foreground truncate text-xs">{user.email}</span>
                </span>
                <SignOutIcon />
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>
      <SidebarInset>
        <header className="border-border bg-background/85 sticky top-0 z-30 flex h-14 items-center gap-3 border-b px-4 backdrop-blur-xl md:px-6">
          <SidebarTrigger />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">Account administration</p>
            <p className="text-muted-foreground hidden text-xs sm:block">
              Provision access without exposing infrastructure controls.
            </p>
          </div>
        </header>
        {children}
      </SidebarInset>
    </SidebarProvider>
  );
}
