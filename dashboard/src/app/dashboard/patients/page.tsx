"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { useQuery } from "@tanstack/react-query"
import { Users2, MessageSquare } from "lucide-react"

import { useMe } from "@/hooks/useMe"
import api from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card"
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table"

// ─── Types ─────────────────────────────────────────────────────────────────────

interface PatientSummary {
  id: string
  phone_number: string
  name: string | null
  age: number | null
  gender: string | null
  last_visit_at: string | null
  record_count: number
}

// ─── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso: string | null): string {
  if (!iso) return "—"
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(iso))
}

function isThisMonth(iso: string | null): boolean {
  if (!iso) return false
  const d = new Date(iso)
  const now = new Date()
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()
}

// ─── Stat Cards ────────────────────────────────────────────────────────────────

function StatCards({ patients }: { patients: PatientSummary[] }) {
  const total = patients.length
  const activeThisMonth = patients.filter((p) => isThisMonth(p.last_visit_at)).length
  const avgRecords =
    total === 0
      ? 0
      : Math.round(
          patients.reduce((sum, p) => sum + p.record_count, 0) / total
        )

  const stats = [
    { label: "Total Patients", value: total },
    { label: "Active This Month", value: activeThisMonth },
    { label: "Avg Records Per Patient", value: avgRecords },
  ]

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {stats.map((s) => (
        <Card key={s.label}>
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground">{s.label}</p>
            <p className="mt-1 text-2xl font-semibold">{s.value}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function StatCardSkeletons() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <CardContent className="pt-6">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="mt-2 h-8 w-16" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

// ─── Skeleton Table ────────────────────────────────────────────────────────────

function TableSkeletonRows() {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <TableRow key={i}>
          {Array.from({ length: 5 }).map((__, j) => (
            <TableCell key={j}>
              <Skeleton className="h-4 w-full" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  )
}

// ─── Page ──────────────────────────────────────────────────────────────────────

export default function PatientsPage() {
  const router = useRouter()
  const { data: me } = useMe()
  const clinicId = me?.clinic?.id ?? ""

  const [searchInput, setSearchInput] = React.useState("")
  const [debouncedSearch, setDebouncedSearch] = React.useState("")

  // 300 ms debounce
  React.useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchInput), 300)
    return () => clearTimeout(t)
  }, [searchInput])

  const {
    data: patients,
    isLoading,
    isError,
  } = useQuery<PatientSummary[]>({
    queryKey: ["patients", clinicId, debouncedSearch],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (debouncedSearch) params.set("search", debouncedSearch)
      const { data } = await api.get<PatientSummary[]>(
        `/api/clinics/${clinicId}/patients${params.toString() ? `?${params}` : ""}`
      )
      return data
    },
    enabled: Boolean(clinicId),
  })

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-xl font-semibold">Patients</h1>
        <p className="text-sm text-muted-foreground">
          All patients who have messaged your clinic via WhatsApp
        </p>
      </div>

      {/* Stat cards */}
      {isLoading || !patients ? (
        <StatCardSkeletons />
      ) : (
        <StatCards patients={patients} />
      )}

      {/* Search + table */}
      <Card>
        <CardHeader className="border-b">
          <div className="flex items-center justify-between gap-4">
            <CardTitle>Patient List</CardTitle>
            <Input
              placeholder="Search by name or phone…"
              className="max-w-xs"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
            />
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {isError ? (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <p className="text-sm text-destructive">
                Failed to load patients. Please try again.
              </p>
            </div>
          ) : isLoading ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Phone</TableHead>
                  <TableHead>Last Visit</TableHead>
                  <TableHead>Total Records</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableSkeletonRows />
              </TableBody>
            </Table>
          ) : !patients || patients.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <MessageSquare className="size-10 text-muted-foreground/40" />
              <p className="text-sm font-medium text-muted-foreground">
                No patients yet.
              </p>
              <p className="max-w-xs text-xs text-muted-foreground">
                Patients appear here after their first WhatsApp message.
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Phone</TableHead>
                  <TableHead>Last Visit</TableHead>
                  <TableHead>Total Records</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {patients.map((patient) => (
                  <TableRow key={patient.id}>
                    <TableCell className="font-medium">
                      {patient.name ?? "Unknown"}
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {patient.phone_number}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatDate(patient.last_visit_at)}
                    </TableCell>
                    <TableCell>{patient.record_count}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          router.push(`/dashboard/patients/${patient.id}`)
                        }
                      >
                        View
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
