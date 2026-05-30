import { redirect } from "next/navigation";
import { headers } from "next/headers";
import Link from "next/link";
import { ChevronLeft, ShieldCheck } from "lucide-react";

async function getMe(): Promise<{ role: string } | null> {
  const headerStore = await headers();
  const cookie = headerStore.get("cookie") ?? "";

  try {
    const res = await fetch(
      `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/auth/me`,
      {
        headers: { cookie },
        cache: "no-store",
      }
    );
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const me = await getMe();

  if (!me || me.role !== "superadmin") {
    redirect("/dashboard");
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Top bar */}
      <header className="sticky top-0 z-50 border-b bg-card shadow-sm">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <ShieldCheck className="size-5 text-primary" />
            <span className="text-base font-semibold text-foreground">
              Super Admin
            </span>
          </div>

          <Link
            href="/dashboard"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ChevronLeft className="size-4" />
            Back to Dashboard
          </Link>
        </div>
      </header>

      {/* Page content */}
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {children}
      </main>
    </div>
  );
}
