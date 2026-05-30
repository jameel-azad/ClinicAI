export default function AuthLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen bg-slate-100 dark:bg-slate-900 flex flex-col items-center justify-center px-4 py-12">
      <div className="mb-8 flex flex-col items-center gap-1">
        <span className="text-3xl font-bold tracking-tight text-primary">ClinicAI</span>
        <span className="text-sm text-muted-foreground">AI-powered clinic management</span>
      </div>
      <div className="w-full max-w-md rounded-2xl border border-border bg-card shadow-md p-8">
        {children}
      </div>
    </div>
  )
}
