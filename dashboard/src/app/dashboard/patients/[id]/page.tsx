"use client"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  ArrowLeft,
  Phone,
  X,
  Plus,
  Save,
  FileText,
  AlertTriangle,
  ExternalLink,
} from "lucide-react"

import { useMe } from "@/hooks/useMe"
import api from "@/lib/api"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card"
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs"
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table"

// ── Types ──────────────────────────────────────────────────────────────────────

interface PatientDetail {
  id: string
  phone_number: string
  name: string | null
  age: number | null
  gender: string | null
  blood_group: string | null
  allergies: string[]
  chronic_conditions: string[]
  current_medications: string[]
  doctor_notes: string | null
  created_at: string
  last_visit_at: string | null
}

interface MedicalRecord {
  id: string
  visit_date: string
  record_type: string
  chief_complaint: string | null
  soap_subjective: string | null
  soap_objective: string | null
  soap_assessment: string | null
  soap_plan: string | null
  soap_confidence: number | null
  diagnoses: Array<{ name: string; snomed_code?: string }> | null
  medications: Array<{ name: string; rxnorm_code?: string; frequency?: string }> | null
  symptoms: Array<{ name: string; severity?: string; duration?: string }> | null
  lab_panel_type: string | null
  lab_results: { all_values: any[]; abnormals: any[]; criticals: any[] } | null
  pdf_url: string | null
  doctor_name: string | null
}

// ── Lab result status color ────────────────────────────────────────────────────

function labStatusClass(status: string): string {
  switch (status?.toUpperCase()) {
    case "HIGH":
      return "text-red-600 font-medium"
    case "LOW":
      return "text-blue-600 font-medium"
    case "CRITICAL":
      return "text-red-900 font-bold"
    case "NORMAL":
      return "text-green-600"
    default:
      return "text-foreground"
  }
}

function labStatusBadgeClass(status: string): string {
  switch (status?.toUpperCase()) {
    case "HIGH":
      return "bg-red-100 text-red-700 border-red-200"
    case "LOW":
      return "bg-blue-100 text-blue-700 border-blue-200"
    case "CRITICAL":
      return "bg-red-200 text-red-900 border-red-400"
    case "NORMAL":
      return "bg-green-100 text-green-700 border-green-200"
    default:
      return ""
  }
}

// ── Editable tag list ──────────────────────────────────────────────────────────

function TagList({
  tags,
  onChange,
  placeholder,
}: {
  tags: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
}) {
  const [input, setInput] = React.useState("")

  function addTag() {
    const trimmed = input.trim()
    if (!trimmed || tags.includes(trimmed)) return
    onChange([...tags, trimmed])
    setInput("")
  }

  function removeTag(tag: string) {
    onChange(tags.filter((t) => t !== tag))
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault()
      addTag()
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap gap-1.5">
        {tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-medium"
          >
            {tag}
            <button
              type="button"
              onClick={() => removeTag(tag)}
              className="text-muted-foreground hover:text-foreground transition-colors"
              aria-label={`Remove ${tag}`}
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-1.5">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder ?? "Add item…"}
          className="h-7 text-xs"
        />
        <Button type="button" size="icon-sm" variant="outline" onClick={addTag} aria-label="Add">
          <Plus className="size-3.5" />
        </Button>
      </div>
    </div>
  )
}

// ── Chip with hover code ───────────────────────────────────────────────────────

function CodeChip({
  label,
  code,
  codeLabel,
}: {
  label: string
  code?: string
  codeLabel?: string
}) {
  const [hovered, setHovered] = React.useState(false)
  return (
    <span
      className="relative inline-flex items-center"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-medium cursor-default">
        {label}
      </span>
      {hovered && code && (
        <span className="absolute bottom-full left-0 z-10 mb-1 whitespace-nowrap rounded-md border border-border bg-popover px-2 py-1 text-xs shadow-md">
          <span className="text-muted-foreground">{codeLabel ?? "Code"}: </span>
          <span className="font-mono font-semibold">{code}</span>
        </span>
      )}
    </span>
  )
}

// ── SOAP section ──────────────────────────────────────────────────────────────

function SoapTabs({ record }: { record: MedicalRecord }) {
  const confidence = record.soap_confidence
  const showWarning = confidence !== null && confidence < 0.7

  return (
    <div className="flex flex-col gap-2">
      {showWarning && (
        <div className="flex items-center gap-2 rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2 text-xs text-yellow-800">
          <AlertTriangle className="size-3.5 shrink-0" />
          AI confidence: {(confidence! * 100).toFixed(0)}% — review carefully
        </div>
      )}
      <Tabs defaultValue="subjective">
        <TabsList variant="line">
          <TabsTrigger value="subjective">Subjective</TabsTrigger>
          <TabsTrigger value="objective">Objective</TabsTrigger>
          <TabsTrigger value="assessment">Assessment</TabsTrigger>
          <TabsTrigger value="plan">Plan</TabsTrigger>
        </TabsList>
        <TabsContent value="subjective">
          <p className="whitespace-pre-wrap text-sm text-foreground/80 pt-2">
            {record.soap_subjective ?? <span className="text-muted-foreground">—</span>}
          </p>
        </TabsContent>
        <TabsContent value="objective">
          <p className="whitespace-pre-wrap text-sm text-foreground/80 pt-2">
            {record.soap_objective ?? <span className="text-muted-foreground">—</span>}
          </p>
        </TabsContent>
        <TabsContent value="assessment">
          <p className="whitespace-pre-wrap text-sm text-foreground/80 pt-2">
            {record.soap_assessment ?? <span className="text-muted-foreground">—</span>}
          </p>
        </TabsContent>
        <TabsContent value="plan">
          <p className="whitespace-pre-wrap text-sm text-foreground/80 pt-2">
            {record.soap_plan ?? <span className="text-muted-foreground">—</span>}
          </p>
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ── Lab results table ─────────────────────────────────────────────────────────

function LabResultsTable({
  labResults,
  panelType,
}: {
  labResults: MedicalRecord["lab_results"]
  panelType: string | null
}) {
  if (!labResults) return null
  const rows = labResults.all_values ?? []

  if (rows.length === 0) return <p className="text-xs text-muted-foreground">No lab values recorded.</p>

  return (
    <div className="flex flex-col gap-1">
      {panelType && (
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          {panelType}
        </p>
      )}
      <div className="overflow-x-auto rounded-md border border-border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Test</TableHead>
              <TableHead>Value</TableHead>
              <TableHead>Unit</TableHead>
              <TableHead>Reference</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row: any, i: number) => (
              <TableRow key={i}>
                <TableCell className="text-xs font-medium">{row.test_name ?? row.name ?? "—"}</TableCell>
                <TableCell className={cn("text-xs font-mono", labStatusClass(row.status))}>
                  {row.value ?? "—"}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">{row.unit ?? "—"}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{row.reference_range ?? row.reference ?? "—"}</TableCell>
                <TableCell>
                  {row.status && (
                    <span
                      className={cn(
                        "inline-flex h-5 items-center rounded-full border px-2 text-[10px] font-semibold uppercase",
                        labStatusBadgeClass(row.status)
                      )}
                    >
                      {row.status}
                    </span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

// ── Medical record card ────────────────────────────────────────────────────────

function RecordCard({ record }: { record: MedicalRecord }) {
  const isConsultation = record.record_type?.toLowerCase() === "consultation"
  const isLabReport = record.record_type?.toLowerCase() === "lab report" || record.record_type?.toLowerCase() === "lab_report"

  const dateStr = record.visit_date
    ? new Date(record.visit_date).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : "—"

  return (
    <Card className="gap-3">
      <CardHeader className="pb-0">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{dateStr}</span>
            <Badge
              variant={isLabReport ? "outline" : "default"}
              className={isLabReport ? "border-purple-300 text-purple-700 bg-purple-50" : ""}
            >
              {record.record_type ?? "Record"}
            </Badge>
            {record.soap_confidence !== null && record.soap_confidence < 0.7 && (
              <Badge variant="outline" className="border-yellow-300 text-yellow-700 bg-yellow-50 gap-1">
                <AlertTriangle className="size-3" />
                Low confidence
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-2">
            {record.doctor_name && (
              <span className="text-xs text-muted-foreground">Dr. {record.doctor_name}</span>
            )}
            {record.pdf_url && (
              <Button
                variant="outline"
                size="xs"
                asChild
              >
                <a href={record.pdf_url} target="_blank" rel="noopener noreferrer">
                  <FileText className="size-3.5" />
                  PDF
                  <ExternalLink className="size-3" />
                </a>
              </Button>
            )}
          </div>
        </div>
        {record.chief_complaint && (
          <p className="text-sm text-muted-foreground">
            Chief complaint: <span className="text-foreground">{record.chief_complaint}</span>
          </p>
        )}
      </CardHeader>

      <CardContent className="flex flex-col gap-4">
        {/* SOAP — consultations */}
        {isConsultation && (
          <SoapTabs record={record} />
        )}

        {/* Diagnoses */}
        {record.diagnoses && record.diagnoses.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Diagnoses</p>
            <div className="flex flex-wrap gap-1.5">
              {record.diagnoses.map((d, i) => (
                <CodeChip
                  key={i}
                  label={d.name}
                  code={d.snomed_code}
                  codeLabel="SNOMED"
                />
              ))}
            </div>
          </div>
        )}

        {/* Medications */}
        {record.medications && record.medications.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Medications</p>
            <div className="flex flex-wrap gap-1.5">
              {record.medications.map((m, i) => (
                <CodeChip
                  key={i}
                  label={m.frequency ? `${m.name} (${m.frequency})` : m.name}
                  code={m.rxnorm_code}
                  codeLabel="RxNorm"
                />
              ))}
            </div>
          </div>
        )}

        {/* Symptoms */}
        {record.symptoms && record.symptoms.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Symptoms</p>
            <div className="flex flex-wrap gap-1.5">
              {record.symptoms.map((s, i) => {
                const detail = [s.severity, s.duration].filter(Boolean).join(", ")
                return (
                  <span
                    key={i}
                    className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs font-medium"
                  >
                    {s.name}
                    {detail && (
                      <span className="ml-1 text-muted-foreground">({detail})</span>
                    )}
                  </span>
                )
              })}
            </div>
          </div>
        )}

        {/* Lab results */}
        {record.lab_results && (
          <div className="flex flex-col gap-1.5">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Lab Results</p>
            <LabResultsTable labResults={record.lab_results} panelType={record.lab_panel_type} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ── Patient profile skeleton ───────────────────────────────────────────────────

function ProfileSkeleton() {
  return (
    <Card>
      <CardHeader className="border-b">
        <Skeleton className="h-5 w-32" />
      </CardHeader>
      <CardContent className="flex flex-col gap-4 pt-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex flex-col gap-1.5">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-8 w-full" />
          </div>
        ))}
        <Skeleton className="h-8 w-20 mt-2" />
      </CardContent>
    </Card>
  )
}

// ── Timeline skeleton ──────────────────────────────────────────────────────────

function TimelineSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      {Array.from({ length: 3 }).map((_, i) => (
        <Card key={i}>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-5 w-20 rounded-full" />
            </div>
            <Skeleton className="h-3 w-48 mt-1" />
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-16 w-full" />
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function PatientDetailPage() {
  const params = useParams<{ id: string }>()
  const patientId = params.id
  const { data: me } = useMe()
  const clinicId = me?.clinic?.id
  const queryClient = useQueryClient()

  // Fetch patient detail
  const {
    data: patient,
    isLoading: patientLoading,
  } = useQuery<PatientDetail>({
    queryKey: ["patient", clinicId, patientId],
    queryFn: async () => {
      const { data } = await api.get<PatientDetail>(
        `/api/clinics/${clinicId}/patients/${patientId}`
      )
      return data
    },
    enabled: Boolean(clinicId && patientId),
  })

  // Fetch medical records
  const {
    data: records,
    isLoading: recordsLoading,
  } = useQuery<MedicalRecord[]>({
    queryKey: ["patient-records", clinicId, patientId],
    queryFn: async () => {
      const { data } = await api.get<MedicalRecord[]>(
        `/api/clinics/${clinicId}/patients/${patientId}/records`
      )
      return data
    },
    enabled: Boolean(clinicId && patientId),
  })

  // Editable profile state — mirror from server when loaded
  const [name, setName] = React.useState("")
  const [age, setAge] = React.useState<string>("")
  const [gender, setGender] = React.useState("")
  const [bloodGroup, setBloodGroup] = React.useState("")
  const [allergies, setAllergies] = React.useState<string[]>([])
  const [chronicConditions, setChronicConditions] = React.useState<string[]>([])
  const [currentMedications, setCurrentMedications] = React.useState<string[]>([])
  const [doctorNotes, setDoctorNotes] = React.useState("")
  const [profileDirty, setProfileDirty] = React.useState(false)

  // Populate form once patient loads
  React.useEffect(() => {
    if (patient) {
      setName(patient.name ?? "")
      setAge(patient.age != null ? String(patient.age) : "")
      setGender(patient.gender ?? "")
      setBloodGroup(patient.blood_group ?? "")
      setAllergies(patient.allergies ?? [])
      setChronicConditions(patient.chronic_conditions ?? [])
      setCurrentMedications(patient.current_medications ?? [])
      setDoctorNotes(patient.doctor_notes ?? "")
      setProfileDirty(false)
    }
  }, [patient])

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: async () => {
      await api.put(
        `/api/clinics/${clinicId}/patients/${patientId}`,
        {
          name: name || null,
          age: age ? Number(age) : null,
          gender: gender || null,
          blood_group: bloodGroup || null,
          allergies,
          chronic_conditions: chronicConditions,
          current_medications: currentMedications,
          doctor_notes: doctorNotes || null,
        }
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["patient", clinicId, patientId] })
      setProfileDirty(false)
    },
  })

  function markDirty() {
    setProfileDirty(true)
  }

  // Sort records most recent first
  const sortedRecords = React.useMemo(() => {
    if (!records) return []
    return [...records].sort(
      (a, b) => new Date(b.visit_date).getTime() - new Date(a.visit_date).getTime()
    )
  }, [records])

  const whatsappNumber = patient?.phone_number
    ? patient.phone_number.replace(/\D/g, "")
    : null

  const isLoading = patientLoading || !me

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon-sm" asChild>
          <Link href="/dashboard/patients" aria-label="Back to patients">
            <ArrowLeft className="size-4" />
          </Link>
        </Button>
        <div>
          <h1 className="text-xl font-semibold">
            {isLoading ? (
              <Skeleton className="h-6 w-40" />
            ) : (
              patient?.name ?? patient?.phone_number ?? "Patient"
            )}
          </h1>
          <p className="text-sm text-muted-foreground">Patient Detail</p>
        </div>
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left: Profile */}
        <div className="lg:col-span-1">
          {isLoading ? (
            <ProfileSkeleton />
          ) : (
            <Card>
              <CardHeader className="border-b">
                <CardTitle>Patient Profile</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4 pt-4">
                {/* Name */}
                <div className="grid gap-1.5">
                  <Label htmlFor="patient-name" className="text-xs">Full Name</Label>
                  <Input
                    id="patient-name"
                    value={name}
                    onChange={(e) => { setName(e.target.value); markDirty() }}
                    placeholder="Patient name"
                    className="h-8 text-sm"
                  />
                </div>

                {/* Phone / WhatsApp */}
                <div className="grid gap-1.5">
                  <Label className="text-xs">Phone Number</Label>
                  <div className="flex items-center gap-2">
                    <span className="flex-1 rounded-lg border border-input bg-muted/50 px-2.5 py-1.5 font-mono text-sm">
                      {patient?.phone_number ?? "—"}
                    </span>
                    {whatsappNumber && (
                      <Button variant="outline" size="icon-sm" asChild aria-label="Open WhatsApp">
                        <a
                          href={`https://wa.me/${whatsappNumber}`}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <Phone className="size-3.5 text-green-600" />
                        </a>
                      </Button>
                    )}
                  </div>
                </div>

                {/* Age */}
                <div className="grid gap-1.5">
                  <Label htmlFor="patient-age" className="text-xs">Age</Label>
                  <Input
                    id="patient-age"
                    type="number"
                    min={0}
                    max={150}
                    value={age}
                    onChange={(e) => { setAge(e.target.value); markDirty() }}
                    placeholder="Years"
                    className="h-8 text-sm"
                  />
                </div>

                {/* Gender */}
                <div className="grid gap-1.5">
                  <Label htmlFor="patient-gender" className="text-xs">Gender</Label>
                  <Input
                    id="patient-gender"
                    value={gender}
                    onChange={(e) => { setGender(e.target.value); markDirty() }}
                    placeholder="e.g. Male, Female, Other"
                    className="h-8 text-sm"
                  />
                </div>

                {/* Blood group */}
                <div className="grid gap-1.5">
                  <Label htmlFor="patient-blood" className="text-xs">Blood Group</Label>
                  <Input
                    id="patient-blood"
                    value={bloodGroup}
                    onChange={(e) => { setBloodGroup(e.target.value); markDirty() }}
                    placeholder="e.g. A+, O-"
                    className="h-8 text-sm"
                  />
                </div>

                {/* Allergies */}
                <div className="grid gap-1.5">
                  <Label className="text-xs">Allergies</Label>
                  <TagList
                    tags={allergies}
                    onChange={(t) => { setAllergies(t); markDirty() }}
                    placeholder="Add allergy…"
                  />
                </div>

                {/* Chronic Conditions */}
                <div className="grid gap-1.5">
                  <Label className="text-xs">Chronic Conditions</Label>
                  <TagList
                    tags={chronicConditions}
                    onChange={(t) => { setChronicConditions(t); markDirty() }}
                    placeholder="Add condition…"
                  />
                </div>

                {/* Current Medications */}
                <div className="grid gap-1.5">
                  <Label className="text-xs">Current Medications</Label>
                  <TagList
                    tags={currentMedications}
                    onChange={(t) => { setCurrentMedications(t); markDirty() }}
                    placeholder="Add medication…"
                  />
                </div>

                {/* Doctor Notes */}
                <div className="grid gap-1.5">
                  <Label htmlFor="doctor-notes" className="text-xs">Doctor Notes</Label>
                  <Textarea
                    id="doctor-notes"
                    value={doctorNotes}
                    onChange={(e) => { setDoctorNotes(e.target.value); markDirty() }}
                    placeholder="Private notes visible only to doctors…"
                    className="min-h-24 text-sm"
                  />
                </div>

                {/* Save */}
                <Button
                  onClick={() => saveMutation.mutate()}
                  disabled={saveMutation.isPending || !profileDirty}
                  className="mt-1 w-full"
                >
                  <Save className="size-4" />
                  {saveMutation.isPending ? "Saving…" : "Save Changes"}
                </Button>

                {saveMutation.isError && (
                  <p className="text-xs text-destructive">
                    Failed to save. Please try again.
                  </p>
                )}

                {/* Meta info */}
                {patient && (
                  <div className="mt-2 flex flex-col gap-1 border-t border-border pt-3 text-xs text-muted-foreground">
                    <span>
                      Registered:{" "}
                      {new Date(patient.created_at).toLocaleDateString(undefined, {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                      })}
                    </span>
                    {patient.last_visit_at && (
                      <span>
                        Last visit:{" "}
                        {new Date(patient.last_visit_at).toLocaleDateString(undefined, {
                          year: "numeric",
                          month: "short",
                          day: "numeric",
                        })}
                      </span>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        {/* Right: Medical history timeline */}
        <div className="lg:col-span-2">
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold">Medical History</h2>
              {!recordsLoading && sortedRecords.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  {sortedRecords.length} record{sortedRecords.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>

            {recordsLoading ? (
              <TimelineSkeleton />
            ) : sortedRecords.length === 0 ? (
              <Card>
                <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
                  <FileText className="size-10 text-muted-foreground/40" />
                  <p className="text-sm font-medium text-muted-foreground">No medical records yet</p>
                  <p className="max-w-xs text-xs text-muted-foreground">
                    Records will appear here after consultations or lab reports are processed.
                  </p>
                </CardContent>
              </Card>
            ) : (
              <div className="flex flex-col gap-4">
                {sortedRecords.map((record) => (
                  <RecordCard key={record.id} record={record} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
