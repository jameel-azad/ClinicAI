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
import { updateModelConfig } from "@/lib/api";
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

// ── vendor / model catalogue ───────────────────────────────────────────────

const VENDOR_MODELS: Record<string, { value: string; label: string }[]> = {
  Groq: [
    {
      value: "llama-3.3-70b-versatile",
      label: "LLaMA 3.3 70B (Recommended)",
    },
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

const VENDORS = Object.keys(VENDOR_MODELS) as Array<keyof typeof VENDOR_MODELS>;

const API_KEY_LABEL: Record<string, string> = {
  Groq: "Groq API Key",
  Anthropic: "Anthropic API Key",
  OpenAI: "OpenAI API Key",
  Google: "Google AI API Key",
};

// ── schema ─────────────────────────────────────────────────────────────────

const schema = z.object({
  vendor: z.string().min(1, "Select a vendor"),
  model: z.string().min(1, "Select a model"),
  api_key: z.string().min(1, "API key is required"),
});

type FormValues = z.infer<typeof schema>;

// ── component ──────────────────────────────────────────────────────────────

export default function ModelPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: me, isLoading: meLoading } = useMe();
  const clinicId = me?.clinic?.id;

  const { data: config, isLoading: configLoading } =
    useModelConfig(clinicId);

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
      vendor: "Groq",
      model: "llama-3.3-70b-versatile",
      api_key: "",
    },
  });

  const selectedVendor = watch("vendor");

  // Prefill from existing config
  useEffect(() => {
    if (config) {
      reset({
        vendor: config.vendor,
        model: config.model,
        api_key: config.api_key,
      });
    }
  }, [config, reset]);

  // When vendor changes, reset model to first option for that vendor
  useEffect(() => {
    const models = VENDOR_MODELS[selectedVendor];
    if (models?.length) {
      setValue("model", models[0].value);
    }
  }, [selectedVendor, setValue]);

  async function onSubmit(values: FormValues) {
    if (!clinicId) return;
    try {
      await updateModelConfig(clinicId, values);
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      toast.success("AI model configuration saved");
      router.push("/onboarding/twilio");
    } catch {
      toast.error("Failed to save model configuration. Please try again.");
    }
  }

  const isLoading = meLoading || configLoading;

  if (isLoading) {
    return (
      <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  const availableModels = VENDOR_MODELS[selectedVendor] ?? [];

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold">AI Model</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose the LLM that will power your AI receptionist.
        </p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-6">
        {/* Vendor */}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="vendor">Vendor</Label>
          <Controller
            name="vendor"
            control={control}
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="vendor" className="w-full">
                  <SelectValue placeholder="Select vendor" />
                </SelectTrigger>
                <SelectContent>
                  {VENDORS.map((v) => (
                    <SelectItem key={v} value={v}>
                      {v}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
          {errors.vendor && (
            <p className="text-xs text-destructive">{errors.vendor.message}</p>
          )}
        </div>

        {/* Model */}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="model">Model</Label>
          <Controller
            name="model"
            control={control}
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="model" className="w-full">
                  <SelectValue placeholder="Select model" />
                </SelectTrigger>
                <SelectContent>
                  {availableModels.map((m) => (
                    <SelectItem key={m.value} value={m.value}>
                      {m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
          {errors.model && (
            <p className="text-xs text-destructive">{errors.model.message}</p>
          )}
        </div>

        {/* API Key */}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="api_key">
            {API_KEY_LABEL[selectedVendor] ?? "API Key"}
          </Label>
          <Input
            id="api_key"
            type="password"
            placeholder="sk-…"
            autoComplete="off"
            aria-invalid={Boolean(errors.api_key)}
            {...register("api_key")}
          />
          {errors.api_key && (
            <p className="text-xs text-destructive">{errors.api_key.message}</p>
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
