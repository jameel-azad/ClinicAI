"use client"

import * as React from "react"
import { useQueryClient, useMutation } from "@tanstack/react-query"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { CheckCircle2, XCircle, Eye, EyeOff, Zap } from "lucide-react"

import api from "../../../../lib/api"
import { useMe, useModelConfig } from "../../../../lib/hooks"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Separator } from "@/components/ui/separator"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select"

// ─── Types ─────────────────────────────────────────────────────────────────

const VENDOR_MODELS: Record<string, string[]> = {
  groq: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
  openai: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
  anthropic: ["claude-sonnet-4-6", "claude-opus-4", "claude-haiku-3-5"],
  google: ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
}

const STT_MODELS = [
  "whisper-large-v3-turbo",
  "whisper-large-v3",
  "distil-whisper-large-v3-en",
]

// ─── Model Config Schema ────────────────────────────────────────────────────

const configSchema = z.object({
  llm_vendor: z.string().min(1, "Select a vendor"),
  llm_model: z.string().min(1, "Select a model"),
  stt_model: z.string().min(1, "Select an STT model"),
})

type ConfigFormData = z.infer<typeof configSchema>

// ─── API Key Schema ─────────────────────────────────────────────────────────

const apiKeySchema = z.object({
  key: z.string().min(1, "API key is required"),
})

type ApiKeyFormData = z.infer<typeof apiKeySchema>

// ─── Test result type ───────────────────────────────────────────────────────

interface TestResult {
  success: boolean
  latency_ms?: number
  error?: string
}

// ─── Model Config Form ──────────────────────────────────────────────────────

function ModelConfigForm({ clinicId }: { clinicId: string }) {
  const { data: config, isLoading } = useModelConfig(clinicId)
  const queryClient = useQueryClient()
  const [selectedVendor, setSelectedVendor] = React.useState<string>("")

  const updateMutation = useMutation({
    mutationFn: (data: ConfigFormData) =>
      api.put(`/api/clinics/${clinicId}/config`, data).then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["config", clinicId] })
    },
  })

  const {
    handleSubmit,
    setValue,
    watch,
    formState: { errors, isDirty },
    reset,
  } = useForm<ConfigFormData>({
    resolver: zodResolver(configSchema),
    defaultValues: {
      llm_vendor: "",
      llm_model: "",
      stt_model: "",
    },
  })

  // Populate form once config loads
  React.useEffect(() => {
    if (config) {
      reset({
        llm_vendor: config.llm_vendor,
        llm_model: config.llm_model,
        stt_model: config.stt_model,
      })
      setSelectedVendor(config.llm_vendor)
    }
  }, [config, reset])

  const watchedVendor = watch("llm_vendor")
  const watchedModel = watch("llm_model")
  const watchedStt = watch("stt_model")
  const availableModels = VENDOR_MODELS[watchedVendor] ?? []

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    )
  }

  return (
    <form
      onSubmit={handleSubmit((data) => updateMutation.mutate(data))}
      className="space-y-4"
    >
      {/* Current config display */}
      {config && (
        <div className="flex flex-wrap gap-2 rounded-lg border bg-muted/40 p-3">
          <Badge variant="outline" className="capitalize">
            {config.llm_vendor}
          </Badge>
          <Badge variant="secondary">{config.llm_model}</Badge>
          <Badge variant="outline" className="text-xs">
            STT: {config.stt_model}
          </Badge>
        </div>
      )}

      <div className="grid gap-1.5">
        <Label>LLM Vendor</Label>
        <Select
          value={watchedVendor}
          onValueChange={(v) => {
            const val = v ?? ""
            setValue("llm_vendor", val, { shouldDirty: true })
            setValue("llm_model", "", { shouldDirty: true })
            setSelectedVendor(val)
          }}
        >
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Select vendor" />
          </SelectTrigger>
          <SelectContent>
            {Object.keys(VENDOR_MODELS).map((v) => (
              <SelectItem key={v} value={v} className="capitalize">
                {v}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {errors.llm_vendor && (
          <p className="text-xs text-destructive">{errors.llm_vendor.message}</p>
        )}
      </div>

      <div className="grid gap-1.5">
        <Label>LLM Model</Label>
        <Select
          value={watchedModel}
          onValueChange={(v) => setValue("llm_model", v ?? "", { shouldDirty: true })}
          disabled={!watchedVendor}
        >
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Select model" />
          </SelectTrigger>
          <SelectContent>
            {availableModels.map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {errors.llm_model && (
          <p className="text-xs text-destructive">{errors.llm_model.message}</p>
        )}
      </div>

      <div className="grid gap-1.5">
        <Label>Speech-to-Text Model</Label>
        <Select
          value={watchedStt}
          onValueChange={(v) => setValue("stt_model", v ?? "", { shouldDirty: true })}
        >
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Select STT model" />
          </SelectTrigger>
          <SelectContent>
            {STT_MODELS.map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {errors.stt_model && (
          <p className="text-xs text-destructive">{errors.stt_model.message}</p>
        )}
      </div>

      <Button
        type="submit"
        disabled={!isDirty || updateMutation.isPending}
      >
        {updateMutation.isPending ? "Saving…" : "Save Changes"}
      </Button>

      {updateMutation.isSuccess && (
        <p className="text-xs text-green-600">Config updated successfully.</p>
      )}
      {updateMutation.isError && (
        <p className="text-xs text-destructive">
          Failed to update config. Please try again.
        </p>
      )}
    </form>
  )
}

// ─── API Key Row ─────────────────────────────────────────────────────────────

function ApiKeyRow({
  vendor,
  keySet,
  clinicId,
}: {
  vendor: string
  keySet: boolean
  clinicId: string
}) {
  const [showInput, setShowInput] = React.useState(false)
  const [showKey, setShowKey] = React.useState(false)

  const updateKeyMutation = useMutation({
    mutationFn: (key: string) =>
      api
        .put(`/api/clinics/${clinicId}/config/keys`, { vendor, key })
        .then((r) => r.data),
    onSuccess: () => {
      setShowInput(false)
    },
  })

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ApiKeyFormData>({
    resolver: zodResolver(apiKeySchema),
  })

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium capitalize">{vendor}</span>
          {keySet ? (
            <span className="flex items-center gap-1 text-xs text-green-600">
              <CheckCircle2 className="size-3.5" />
              Key set
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <XCircle className="size-3.5" />
              Not configured
            </span>
          )}
        </div>
        <Button
          variant="outline"
          size="xs"
          onClick={() => setShowInput((v) => !v)}
        >
          {showInput ? "Cancel" : keySet ? "Update Key" : "Add Key"}
        </Button>
      </div>

      {showInput && (
        <form
          onSubmit={handleSubmit((data) =>
            updateKeyMutation.mutate(data.key)
          )}
          className="flex gap-2"
        >
          <div className="relative flex-1">
            <Input
              type={showKey ? "text" : "password"}
              placeholder={`${vendor} API key`}
              {...register("key")}
              className="pr-9"
            />
            <button
              type="button"
              onClick={() => setShowKey((v) => !v)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={showKey ? "Hide key" : "Show key"}
            >
              {showKey ? (
                <EyeOff className="size-4" />
              ) : (
                <Eye className="size-4" />
              )}
            </button>
          </div>
          <Button
            type="submit"
            size="sm"
            disabled={updateKeyMutation.isPending}
          >
            {updateKeyMutation.isPending ? "Saving…" : "Save"}
          </Button>
        </form>
      )}
      {errors.key && (
        <p className="text-xs text-destructive">{errors.key.message}</p>
      )}
      {updateKeyMutation.isSuccess && (
        <p className="text-xs text-green-600">Key saved successfully.</p>
      )}
      {updateKeyMutation.isError && (
        <p className="text-xs text-destructive">Failed to save key.</p>
      )}
    </div>
  )
}

// ─── Test Connection ─────────────────────────────────────────────────────────

function TestConnectionButton({ clinicId }: { clinicId: string }) {
  const testMutation = useMutation<TestResult>({
    mutationFn: () =>
      api
        .post(`/api/clinics/${clinicId}/config/test`)
        .then((r) => r.data as TestResult),
  })

  return (
    <div className="space-y-3">
      <Button
        variant="outline"
        onClick={() => testMutation.mutate()}
        disabled={testMutation.isPending}
      >
        <Zap className="size-4" />
        {testMutation.isPending ? "Testing…" : "Test Connection"}
      </Button>

      {testMutation.isSuccess && testMutation.data && (
        <div
          className={`flex items-start gap-3 rounded-lg border p-3 text-sm ${
            testMutation.data.success
              ? "border-green-200 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-950/30 dark:text-green-300"
              : "border-destructive/30 bg-destructive/5 text-destructive"
          }`}
        >
          {testMutation.data.success ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-green-600 dark:text-green-400" />
          ) : (
            <XCircle className="mt-0.5 size-4 shrink-0" />
          )}
          <div className="space-y-0.5">
            <p className="font-medium">
              {testMutation.data.success ? "Connection successful" : "Connection failed"}
            </p>
            {testMutation.data.latency_ms != null && (
              <p className="text-xs opacity-80">
                Latency: {testMutation.data.latency_ms} ms
              </p>
            )}
            {testMutation.data.error && (
              <p className="text-xs opacity-80">{testMutation.data.error}</p>
            )}
          </div>
        </div>
      )}

      {testMutation.isError && (
        <p className="text-xs text-destructive">
          Request failed. Check your network connection.
        </p>
      )}
    </div>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function ConfigPage() {
  const { data: me } = useMe()
  const clinicId = me?.clinic_id ?? ""
  const { data: config, isLoading } = useModelConfig(clinicId)

  const vendors: { name: string; keySet: boolean }[] = [
    { name: "groq", keySet: config?.groq_key_set ?? false },
    { name: "openai", keySet: config?.openai_key_set ?? false },
    { name: "anthropic", keySet: config?.anthropic_key_set ?? false },
    { name: "google", keySet: config?.google_key_set ?? false },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">AI Configuration</h1>
        <p className="text-sm text-muted-foreground">
          Manage your LLM and speech-to-text settings
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Model config */}
        <Card>
          <CardHeader>
            <CardTitle>Model Settings</CardTitle>
            <CardDescription>
              Choose your LLM vendor, model, and STT model.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {clinicId ? (
              <ModelConfigForm clinicId={clinicId} />
            ) : (
              <Skeleton className="h-40 w-full" />
            )}
          </CardContent>
        </Card>

        {/* API keys + test */}
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader>
              <CardTitle>API Keys</CardTitle>
              <CardDescription>
                Set API keys per vendor. Keys are stored encrypted server-side.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {isLoading ? (
                Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))
              ) : (
                vendors.map((v, i) => (
                  <React.Fragment key={v.name}>
                    <ApiKeyRow
                      vendor={v.name}
                      keySet={v.keySet}
                      clinicId={clinicId}
                    />
                    {i < vendors.length - 1 && <Separator />}
                  </React.Fragment>
                ))
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Test Connection</CardTitle>
              <CardDescription>
                Verify that your current model config and API key are working.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {clinicId ? (
                <TestConnectionButton clinicId={clinicId} />
              ) : (
                <Skeleton className="h-8 w-32" />
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
