"use client"

import * as React from "react"
import Link from "next/link"
import { useQuery } from "@tanstack/react-query"
import { Copy, Check, UserPlus, Cpu } from "lucide-react"

import { useMe } from "@/hooks/useMe"
import { useModelConfig } from "@/hooks/useModelConfig"
import { fetchDoctors, type Doctor } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

function StatCardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-4 w-24" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-6 w-40" />
        <Skeleton className="mt-2 h-4 w-28" />
      </CardContent>
    </Card>
  )
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = React.useState(false)

  function handleCopy() {
    navigator.clipboard.writeText(value).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <Button
      variant="ghost"
      size="icon-xs"
      onClick={handleCopy}
      aria-label="Copy to clipboard"
    >
      {copied ? (
        <Check className="size-3 text-green-600" />
      ) : (
        <Copy className="size-3" />
      )}
    </Button>
  )
}

function formatHour(h: number): string {
  const ampm = h >= 12 ? "PM" : "AM"
  const display = h % 12 === 0 ? 12 : h % 12
  return `${display}:00 ${ampm}`
}

export default function OverviewPage() {
  const { data: me, isLoading: meLoading } = useMe()
  const clinicId = me?.clinic?.id
  const { data: config, isLoading: configLoading } = useModelConfig(clinicId)

  const { data: doctors, isLoading: doctorsLoading } = useQuery<Doctor[]>({
    queryKey: ["doctors", clinicId],
    queryFn: () => fetchDoctors(clinicId!),
    enabled: Boolean(clinicId),
  })

  const isLoading = meLoading || configLoading || doctorsLoading
  const activeDoctors = doctors?.length ?? 0

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <Skeleton className="h-7 w-36" />
          <Skeleton className="mt-1 h-4 w-64" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <StatCardSkeleton key={i} />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Overview</h1>
        <p className="text-sm text-muted-foreground">
          Your clinic at a glance
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* Clinic Name */}
        <Card>
          <CardHeader>
            <CardTitle>Clinic Name</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <span className="text-base font-medium">
              {me?.clinic?.name ?? "—"}
            </span>
            <Badge variant="default">Active</Badge>
          </CardContent>
        </Card>

        {/* WhatsApp Number */}
        <Card>
          <CardHeader>
            <CardTitle>WhatsApp Number</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm">
                {me?.clinic?.twilio_whatsapp_number ?? "Not configured"}
              </span>
              {me?.clinic?.twilio_whatsapp_number && (
                <CopyButton value={me.clinic.twilio_whatsapp_number} />
              )}
            </div>
            <CardDescription>Twilio WhatsApp line</CardDescription>
          </CardContent>
        </Card>

        {/* AI Model */}
        <Card>
          <CardHeader>
            <CardTitle>AI Model</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {config ? (
              <>
                <Badge variant="outline" className="w-fit capitalize">
                  {config.llm_vendor}
                </Badge>
                <span className="text-sm font-medium">{config.llm_model}</span>
                {config.stt_model && (
                  <span className="text-xs text-muted-foreground">
                    STT: {config.stt_model}
                  </span>
                )}
              </>
            ) : (
              <span className="text-sm text-muted-foreground">
                Not configured
              </span>
            )}
          </CardContent>
        </Card>

        {/* Doctors */}
        <Card>
          <CardHeader>
            <CardTitle>Doctors</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <span className="text-2xl font-semibold">{activeDoctors}</span>
            <CardDescription>doctors registered</CardDescription>
          </CardContent>
        </Card>

        {/* Working Hours */}
        <Card>
          <CardHeader>
            <CardTitle>Working Hours</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {me?.clinic?.opening_hour != null &&
            me?.clinic?.closing_hour != null ? (
              <>
                <span className="text-sm font-medium">
                  {formatHour(me.clinic.opening_hour)} &mdash;{" "}
                  {formatHour(me.clinic.closing_hour)}
                </span>
                <CardDescription>{me.clinic.timezone}</CardDescription>
              </>
            ) : (
              <span className="text-sm text-muted-foreground">
                Not configured
              </span>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick actions */}
      <div className="flex flex-wrap gap-3">
        <Button asChild>
          <Link href="/dashboard/doctors">
            <UserPlus className="size-4" />
            Add Doctor
          </Link>
        </Button>
        <Button variant="outline" asChild>
          <Link href="/dashboard/config">
            <Cpu className="size-4" />
            Change AI Model
          </Link>
        </Button>
      </div>
    </div>
  )
}
