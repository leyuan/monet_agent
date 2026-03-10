"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BarChart3, Bot, BookOpen, Activity, LogOut, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { createClient } from "@/lib/supabase/client";
import { EventCalendar } from "@/components/trading/event-calendar";

const navItems = [
  { href: "/about", label: "About Me", icon: User },
  { href: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { href: "/chat", label: "Chat", icon: Bot },
  { href: "/journal", label: "Journal", icon: BookOpen },
  { href: "/activity", label: "Activity", icon: Activity },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  const handleSignOut = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
  };

  return (
    <div className="flex h-dvh">
      <aside className="hidden w-56 flex-col border-r bg-background md:flex">
        <div className="flex h-14 items-center border-b px-4">
          <h2 className="font-semibold text-sm">Monet Agent</h2>
        </div>
        <nav className="flex flex-col gap-1 p-2">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = pathname.startsWith(item.href);
            return (
              <Link key={item.href} href={item.href}>
                <Button
                  variant="ghost"
                  className={cn(
                    "w-full justify-start gap-2 text-sm",
                    isActive && "bg-muted",
                  )}
                >
                  <Icon className="size-4" />
                  {item.label}
                </Button>
              </Link>
            );
          })}
        </nav>
        <div className="flex-1 overflow-y-auto border-t">
          <EventCalendar />
        </div>
        <div className="border-t p-2">
          <Button variant="ghost" className="w-full justify-start gap-2 text-sm" onClick={handleSignOut}>
            <LogOut className="size-4" />
            Sign Out
          </Button>
        </div>
      </aside>
      <main className="flex-1 overflow-hidden pb-14 md:pb-0">{children}</main>
      {/* Mobile bottom tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-50 flex items-center justify-around border-t bg-background md:hidden">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] text-muted-foreground transition-colors",
                isActive && "text-foreground",
              )}
            >
              <Icon className="size-5" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
