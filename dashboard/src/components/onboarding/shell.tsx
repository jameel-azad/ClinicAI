"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";
import { StepsSidebar } from "./steps-sidebar";

/**
 * Client-side auth guard + layout shell for the onboarding wizard.
 * Because the token lives in localStorage we must check it on the client.
 */
export function OnboardingShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (mounted && !isAuthenticated()) {
      router.replace("/auth/login");
    }
  }, [mounted, router]);

  if (!mounted) return null;
  if (!isAuthenticated()) return null;

  return (
    <div className="flex min-h-screen bg-background">
      {/* Left sidebar */}
      <aside className="hidden w-64 shrink-0 border-r md:flex md:flex-col">
        <div className="flex h-16 items-center border-b px-6">
          <span className="text-base font-semibold tracking-tight">
            ClinicAI
          </span>
        </div>
        <StepsSidebar />
      </aside>

      {/* Main content */}
      <main className="flex flex-1 flex-col overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl flex-1 px-6 py-10">
          {children}
        </div>
      </main>
    </div>
  );
}
