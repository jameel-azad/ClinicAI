"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";

import { useMe } from "@/hooks/useMe";
import { useModelConfig } from "@/hooks/useModelConfig";
import { updateModelConfig, type ModelConfigUpdatePayload } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// ── catalogues ─────────────────────────────────────────────────────────────

const LLM_VENDOR_MODELS: Record<string, { value: string; label: string }[]> = {
  Groq: [
    { value: "llama-3.3-70b-versatile", label: "LLaMA 3.3 70B (Recommended)" },
  ],
  Anthropic: [
    { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
    { value: "claude-haiku-4-5-20251001", label: "Claude Haiku 4.5" },
  ],
  OpenAI: [
    { value: "gpt-4o", label: "GPT-4o" },
    { value: "gpt-4o-mini", label: "GPT-4o mini" },
  ],
  Google: [
    { value: "gemini-2.5-flash", label: "Gemini 2.5 Flash" },
    { value: "gemini-2.0-flash", label: "Gemini 2.0 Flash" },
  ],
};

const STT_VENDOR_MODELS: Record<string, { value: string; label: string }[]> = {
  Groq: [
    { value: "whisper-large-v3-turbo", label: "Whisper Large v3 Turbo (Recommended)" },
    { value: "whisper-large-v3", label: "Whisper Large v3" },
  ],
  OpenAI: [
    { value: "whisper-1", label: "Whisper-1" },
  ],
};

const LLM_VENDORS = Object.keys(LLM_VENDOR_MODELS);
const STT_VENDORS = Object.keys(STT_VENDOR_MODELS);

const VENDOR_API_FIELD: Record<string, keyof ModelConfigUpdatePayload> = {
  Groq: "groq_api_key",
  Anthropic: "anthropic_api_key",
  OpenAI: "openai_api_key",
  Google: "google_api_key",
};

const API_KEY_LABEL: Record<string, string> = {
  Groq: "Groq API Key",
  Anthropic: "Anthropic API Key",
  OpenAI: "OpenAI API Key",
  Google: "Google AI API Key",
};

// ── schema ─────────────────────────────────────────────────────────────────

const schema = z.object({
  llm_vendor: z.string().min(1, "Select a vendor"),
  llm_model: z.string().min(1, "Select a model"),
  llm_api_key: z.string().min(1, "API key is required"),
  stt_vendor: z.string().min(1, "Select a STT vendor"),
  stt_model: z.string().min(1, "Select a STT model"),
  stt_api_key: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

// ── component ──────────────────────────────────────────────────────────────

export default function ModelPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: me, isLoading: meLoading } = useMe();
  const clinicId = me?.clinic?.id;

  const { data: config, isLoading: configLoading } = useModelConfig(clinicId);

  const {
    register,
    handleSubmit,
    control,
    watch,
    reset,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      llm_vendor: "Groq",
      llm_model: "llama-3.3-70b-versatile",
      llm_api_key: "",
      stt_vendor: "Groq",
      stt_model: "whisper-large-v3-turbo",
      stt_api_key: "",
    },
  });

  const selectedLlmVendor = watch("llm_vendor");
  const selectedSttVendor = watch("stt_vendor");
  const sameVendor = selectedLlmVendor === selectedSttVendor;

  // Prefill from existing config
  useEffect(() => {
    if (config) {
      reset({
        llm_vendor: config.vendor ?? "Groq",
        llm_model: config.model ?? "llama-3.3-70b-versatile",
        llm_api_key: "",
        stt_vendor: "Groq",
        stt_model: "whisper-large-v3-turbo",
        stt_api_key: "",
      });
    }
  }, [config, reset]);

  // Reset LLM model when vendor changes
  useEffect(() => {
    const models = LLM_VENDOR_MODELS[selectedLlmVendor];
    if (models?.length) setValue("llm_model", models[0].value);
  }, [selectedLlmVendor, setValue]);

  // Reset STT model when STT vendor changes
  useEffect(() => {
    const models = STT_VENDOR_MODELS[selectedSttVendor];
    if (models?.length) setValue("stt_model", models[0].value);
  }, [selectedSttVendor, setValue]);

  async function onSubmit(values: FormValues) {
    if (!clinicId) return;
    try {
      const llmKeyField = VENDOR_API_FIELD[values.llm_vendor] ?? "groq_api_key";
      const sttKeyField = VENDOR_API_FIELD[values.stt_vendor] ?? "groq_api_key";

      const payload: ModelConfigUpdatePayload = {
        llm_vendor: values.llm_vendor.toLowerCase(),
        llm_model: values.llm_model,
        stt_vendor: values.stt_vendor.toLowerCase(),
        stt_model: values.stt_model,
        [llmKeyField]: values.llm_api_key,
      };

      // Only add STT key if it's a different vendor (otherwise same key already set above)
      if (!sameVendor && values.stt_api_key?.trim()) {
        payload[sttKeyField] = values.stt_api_key.trim();
      }

      await updateModelConfig(clinicId, payload);
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      toast.success("AI model configuration saved");
      router.push("/onboarding/twilio");
    } catch {
      toast.error("Failed to save model configuration. Please try again.");
    }
  }

  if (meLoading || configLoading) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  const availableLlmModels = LLM_VENDOR_MODELS[selectedLlmVendor] ?? [];
  const availableSttModels = STT_VENDOR_MODELS[selectedSttVendor] ?? [];

  return (
    <div className="flex flex-col gap-10">
      <div>
        <h1 className="text-2xl font-semibold">AI Models</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Configure your general-purpose LLM and speech-to-text model independently.
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-10">

        {/* ── Section 1: General Purpose LLM ─────────────────────────────── */}
        <div className="flex flex-col gap-4">
          <div>
            <h2 className="text-base font-medium">General Purpose LLM</h2>
            <p className="text-xs text-muted-foreground">Used for conversations, booking, and routing.</p>
          </div>

          {/* LLM Vendor */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="llm_vendor">Vendor</Label>
            <Controller
              name="llm_vendor"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="llm_vendor" className="w-full">
                    <SelectValue placeholder="Select vendor" />
                  </SelectTrigger>
                  <SelectContent>
                    {LLM_VENDORS.map((v) => (
                      <SelectItem key={v} value={v}>{v}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            {errors.llm_vendor && (
              <p className="text-xs text-destructive">{errors.llm_vendor.message}</p>
            )}
          </div>

          {/* LLM Model */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="llm_model">Model</Label>
            <Controller
              name="llm_model"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="llm_model" className="w-full">
                    <SelectValue placeholder="Select model" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableLlmModels.map((m) => (
                      <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            {errors.llm_model && (
              <p className="text-xs text-destructive">{errors.llm_model.message}</p>
            )}
          </div>

          {/* LLM API Key */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="llm_api_key">
              {API_KEY_LABEL[selectedLlmVendor] ?? "API Key"}
            </Label>
            <Input
              id="llm_api_key"
              type="password"
              placeholder="sk-…"
              autoComplete="off"
              aria-invalid={Boolean(errors.llm_api_key)}
              {...register("llm_api_key")}
            />
            {errors.llm_api_key && (
              <p className="text-xs text-destructive">{errors.llm_api_key.message}</p>
            )}
          </div>
        </div>

        {/* ── Section 2: STT Model ────────────────────────────────────────── */}
        <div className="flex flex-col gap-4">
          <div>
            <h2 className="text-base font-medium">Speech-to-Text (STT)</h2>
            <p className="text-xs text-muted-foreground">Used to transcribe voice messages from patients.</p>
          </div>

          {/* STT Vendor */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="stt_vendor">Vendor</Label>
            <Controller
              name="stt_vendor"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="stt_vendor" className="w-full">
                    <SelectValue placeholder="Select STT vendor" />
                  </SelectTrigger>
                  <SelectContent>
                    {STT_VENDORS.map((v) => (
                      <SelectItem key={v} value={v}>{v}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            {errors.stt_vendor && (
              <p className="text-xs text-destructive">{errors.stt_vendor.message}</p>
            )}
          </div>

          {/* STT Model */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="stt_model">Model</Label>
            <Controller
              name="stt_model"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="stt_model" className="w-full">
                    <SelectValue placeholder="Select STT model" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableSttModels.map((m) => (
                      <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
            {errors.stt_model && (
              <p className="text-xs text-destructive">{errors.stt_model.message}</p>
            )}
          </div>

          {/* STT API Key — only if different vendor from LLM */}
          {!sameVendor && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="stt_api_key">
                {API_KEY_LABEL[selectedSttVendor] ?? "API Key"}
              </Label>
              <Input
                id="stt_api_key"
                type="password"
                placeholder="sk-…"
                autoComplete="off"
                {...register("stt_api_key")}
              />
              <p className="text-xs text-muted-foreground">
                Different vendor from your LLM — a separate API key is needed.
              </p>
            </div>
          )}

          {sameVendor && (
            <p className="text-xs text-muted-foreground">
              Same vendor as your LLM — the same API key will be used for STT.
            </p>
          )}
        </div>

        <div className="flex justify-end">
          <Button type="submit" disabled={isSubmitting} size="lg">
            {isSubmitting ? "Saving…" : "Save & Continue"}
          </Button>
        </div>
      </form>
    </div>
  );
}
