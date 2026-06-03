export interface Clinic {
  id: string; name: string; twilio_number: string; timezone: string
  open_hour: number; close_hour: number; is_active: boolean; created_at: string
}
export interface ClinicUser {
  id: string; email: string; full_name: string; role: 'admin' | 'superadmin'
  clinic_id: string | null; is_active: boolean; created_at: string
  clinic_name?: string; clinic_twilio_number?: string; clinic_timezone?: string
  clinic_open_hour?: number; clinic_close_hour?: number
}
export interface Doctor {
  id: string; clinic_id: string; name: string; specialty: string
  whatsapp_number: string; working_hours_start: number; working_hours_end: number
  appointment_duration_minutes: number; buffer_minutes: number; is_active: boolean
}
export interface ModelConfig {
  id: string; clinic_id: string; llm_vendor: string; llm_model: string
  stt_vendor: string; stt_model: string; updated_at: string
  groq_api_key_set: boolean; anthropic_api_key_set: boolean
  openai_api_key_set: boolean; google_api_key_set: boolean
}
export interface AuthResponse {
  access_token: string; token_type: string; clinic_id: string; user_id: string
}
