"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { LayoutDashboard, Users, Users2, Settings, BookOpen, Menu, LogOut, Stethoscope } from "lucide-react"

import { isAuthenticated, removeToken } from "@/lib/auth"
import { useMe } from "@/hooks/useMe"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu"
import {
  Sheet,
  SheetTrigger,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"

const navLinks = [
  { label: "Overview", href: "/dashboard", icon: LayoutDashboard, exact: true },
  { label: "Doctors", href: "/dashboard/doctors", icon: Users, exact: false },
  { label: "Patients", href: "/dashboard/patients", icon: Users2, exact: false },
  { label: "AI Config", href: "/dashboard/config", icon: Settings, exact: false },
  { label: "Documentation", href: "/docs", icon: BookOpen, exact: false },
]

function NavLink({
  href,
  icon: Icon,
  label,
  exact,
  pathname,
  onClick,
}: {
  href: string
  icon: React.ElementType
  label: string
  exact: boolean
  pathname: string
  onClick?: () => void
}) {
  const active = exact ? pathname === href : pathname.startsWith(href)
  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-sidebar-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
      )}
    >
      <Icon className="size-4 shrink-0" />
      {label}
    </Link>
  )
}

function SidebarContent({
  pathname,
  onLinkClick,
}: {
  pathname: string
  onLinkClick?: () => void
}) {
  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex items-center gap-2 px-3 py-4">
        <Stethoscope className="size-6 text-sidebar-primary" />
        <span className="font-heading text-base font-semibold text-sidebar-foreground">
          ClinicAI
        </span>
      </div>
      <nav className="flex flex-col gap-1 px-2">
        {navLinks.map((link) => (
          <NavLink
            key={link.href}
            {...link}
            pathname={pathname}
            onClick={onLinkClick}
          />
        ))}
      </nav>
    </div>
  )
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = React.useState(false)
  const { data: me } = useMe()

  React.useEffect(() => {
    if (!isAuthenticated()) {
      router.push("/auth/login")
    }
  }, [router])

  function handleSignOut() {
    removeToken()
    router.push("/auth/login")
  }

  const displayName = me?.email ?? ""
  const initials = displayName
    ? displayName.slice(0, 2).toUpperCase()
    : "?"

  return (
    <div className="flex min-h-screen bg-background">
      {/* Desktop sidebar */}
      <aside className="hidden w-56 shrink-0 border-r border-sidebar-border bg-sidebar md:flex md:flex-col">
        <SidebarContent pathname={pathname} />
      </aside>

      {/* Mobile sidebar */}
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="w-56 bg-sidebar p-0">
          <SheetHeader className="sr-only">
            <SheetTitle>Navigation</SheetTitle>
          </SheetHeader>
          <SidebarContent
            pathname={pathname}
            onLinkClick={() => setMobileOpen(false)}
          />
        </SheetContent>
      </Sheet>

      {/* Main area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b bg-background px-4">
          <div className="flex items-center gap-3">
            {/* Hamburger — opens Sheet */}
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation"
            >
              <Menu className="size-5" />
            </Button>
            <span className="text-sm font-medium text-muted-foreground">
              {me?.clinic?.name ?? ""}
            </span>
          </div>

          {/* User avatar dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="ghost" size="icon" aria-label="User menu"><Avatar size="sm"><AvatarFallback>{initials}</AvatarFallback></Avatar></Button>} />
            <DropdownMenuContent align="end" side="bottom" sideOffset={8}>
              <div className="px-1.5 py-1">
                <p className="text-sm font-medium">{me?.email}</p>
              </div>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onClick={handleSignOut}>
                <LogOut className="size-4" />
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-6">{children}</main>
      </div>
    </div>
  )
}
