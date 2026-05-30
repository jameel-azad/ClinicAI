import Link from "next/link";

const navLinks = [
  { href: "/docs/getting-started", label: "Getting Started" },
  { href: "/docs/patient-guide", label: "Patient Guide" },
  { href: "/docs/doctor-guide", label: "Doctor Guide" },
  { href: "/docs/ai-models", label: "AI Models" },
  { href: "/docs/twilio-setup", label: "Twilio Setup" },
];

export default function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-white">
      {/* Top bar */}
      <header className="border-b border-zinc-200 px-6 py-4 flex items-center gap-4">
        <Link href="/" className="font-semibold text-zinc-900 text-lg">
          ClinicAI
        </Link>
        <span className="text-zinc-300">/</span>
        <span className="text-zinc-500 text-sm">Documentation</span>
      </header>

      <div className="flex">
        {/* Left nav */}
        <aside className="w-56 shrink-0 border-r border-zinc-200 min-h-[calc(100vh-57px)] px-4 py-8">
          <p className="text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-3 px-2">
            Docs
          </p>
          <nav className="flex flex-col gap-1">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="rounded-md px-2 py-1.5 text-sm text-zinc-700 hover:bg-zinc-100 hover:text-zinc-900 transition-colors"
              >
                {link.label}
              </Link>
            ))}
          </nav>
        </aside>

        {/* Right content */}
        <main className="flex-1 px-10 py-10 max-w-3xl">{children}</main>
      </div>
    </div>
  );
}
