import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from './api'
import { ClinicUser, Doctor, ModelConfig } from '../types'

export const useMe = () => useQuery<ClinicUser>({
  queryKey: ['me'],
  queryFn: () => api.get('/api/auth/me').then(r => r.data),
  retry: false,
})

export const useDoctors = (clinicId: string) => useQuery<Doctor[]>({
  queryKey: ['doctors', clinicId],
  queryFn: () => api.get(`/api/clinics/${clinicId}/doctors`).then(r => r.data),
  enabled: !!clinicId,
})

export const useModelConfig = (clinicId: string) => useQuery<ModelConfig>({
  queryKey: ['config', clinicId],
  queryFn: () => api.get(`/api/clinics/${clinicId}/config`).then(r => r.data),
  enabled: !!clinicId,
})
