/**
 * Typed API client built on top of axios.
 * All requests add the auth token from localStorage automatically.
 * A 401 response clears the token and redirects to /auth/login.
 */
import axios from "axios";
import { getToken, removeToken } from "./auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const client = axios.create({ baseURL: API_BASE });

client.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401 && typeof window !== "undefined") {
      removeToken();
      window.location.href = "/auth/login";
    }
    return Promise.reject(error);
  }
);

export default client;

// ── types ──────────────────────────────────────────────────────────────────

export interface Clinic {
  id: string;
  name: string;
  timezone: string;
  opening_hour: number;
  closing_hour: number;
  twilio_whatsapp_number?: string;
}

export interface Doctor {
  id: string;
  name: string;
  specialty: string;
  whatsapp_number: string;
  working_hours_start: number;
  working_hours_end: number;
  appointment_duration: number;
  buffer_minutes: number;
  google_calendar_id?: string | null;
}

export interface ModelConfig {
  vendor: string;
  model: string;
  api_key: string;
}

export interface ModelConfigUpdatePayload {
  llm_vendor?: string;
  llm_model?: string;
  stt_vendor?: string;
  stt_model?: string;
  groq_api_key?: string;
  anthropic_api_key?: string;
  openai_api_key?: string;
  google_api_key?: string;
}

export interface Me {
  id: string;
  email: string;
  clinic: Clinic;
  doctors: Doctor[];
  model_config?: ModelConfig;
}

// ── endpoints ──────────────────────────────────────────────────────────────

export async function fetchMe(): Promise<Me> {
  const { data } = await client.get<any>("/api/auth/me");
  
  const clinic = data.clinic_id ? {
    id: data.clinic_id,
    name: data.clinic_name || "",
    timezone: data.clinic_timezone || "Asia/Kolkata",
    opening_hour: data.clinic_open_hour || 9,
    closing_hour: data.clinic_close_hour || 18,
    twilio_whatsapp_number: data.clinic_twilio_number || undefined,
  } : null;

  return {
    id: data.id,
    email: data.email,
    clinic: clinic as unknown as Clinic, // The UI assumes clinic is always present for admins
    doctors: [], // The backend /me doesn't return this, it should be fetched separately
  };
}

export async function updateClinic(
  clinicId: string,
  payload: Partial<Omit<Clinic, "id">>
): Promise<Clinic> {
  const { data } = await client.put<Clinic>(`/api/clinics/${clinicId}`, payload);
  return data;
}

export async function fetchDoctors(clinicId: string): Promise<Doctor[]> {
  const { data } = await client.get<Doctor[]>(`/api/clinics/${clinicId}/doctors`);
  return data;
}

export async function createDoctor(
  clinicId: string,
  payload: Omit<Doctor, "id">
): Promise<Doctor> {
  const { data } = await client.post<Doctor>(
    `/api/clinics/${clinicId}/doctors`,
    payload
  );
  return data;
}

export async function fetchModelConfig(clinicId: string): Promise<ModelConfig> {
  const { data } = await client.get<ModelConfig>(`/api/clinics/${clinicId}/config`);
  return data;
}

export async function updateModelConfig(
  clinicId: string,
  payload: ModelConfigUpdatePayload
): Promise<ModelConfig> {
  const { data } = await client.put<ModelConfig>(
    `/api/clinics/${clinicId}/config`,
    payload
  );
  return data;
}

export async function testTwilio(clinicId: string): Promise<{ success: boolean; message: string }> {
  const { data } = await client.post<{ success: boolean; message: string }>(
    `/api/clinics/${clinicId}/config/test`
  );
  return data;
}
