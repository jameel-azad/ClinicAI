"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CheckIcon } from "lucide-react";
import { cn } from "@/lib/utils";

const STEPS = [
  { label: "Clinic Details", href: "/onboarding/clinic" },
  { label: "Add Doctors", href: "/onboarding/doctors" },
  { label: "AI Model", href: "/onboarding/model" },
  { label: "Twilio Setup", href: "/onboarding/twilio" },
  { label: "Go Live", href: "/onboarding/done" },
];

function getStepState(
  stepHref: string,
  currentPathname: string,
  stepIndex: number,
  activeIndex: number
): "completed" | "active" | "pending" {
  if (stepIndex < activeIndex) return "completed";
  if (stepHref === currentPathname || stepIndex === activeIndex) return "active";
  return "pending";
}

export function StepsSidebar() {
  const pathname = usePathname();
  const activeIndex = STEPS.findIndex((s) => s.href === pathname);

  return (
    <nav
      aria-label="Onboarding steps"
      className="flex flex-col gap-1 py-8 px-6"
    >
      <p className="mb-6 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
        Setup
      </p>
      <ol className="flex flex-col gap-2">
        {STEPS.map((step, idx) => {
          const state = getStepState(step.href, pathname ?? "", idx, activeIndex);
          const isCompleted = state === "completed";
          const isActive = state === "active";

          return (
            <li key={step.href}>
              <Link
                href={step.href}
                aria-current={isActive ? "step" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  isActive &&
                    "bg-primary/10 text-primary",
                  isCompleted &&
                    "text-foreground hover:bg-muted",
                  !isActive &&
                    !isCompleted &&
                    "text-muted-foreground hover:text-foreground hover:bg-muted"
                )}
              >
                {/* Step indicator */}
                <span
                  className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
                    isCompleted &&
                      "border-transparent bg-primary text-primary-foreground",
                    isActive &&
                      "border-primary bg-primary/10 text-primary",
                    !isActive &&
                      !isCompleted &&
                      "border-border bg-background text-muted-foreground"
                  )}
                >
                  {isCompleted ? (
                    <CheckIcon className="size-3.5" />
                  ) : (
                    <span>{idx + 1}</span>
                  )}
                </span>
                {step.label}
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
