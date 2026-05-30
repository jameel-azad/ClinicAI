'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useForm, Controller } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { toast } from 'sonner'
import { Loader2 } from 'lucide-react'
import api from '@/lib/api'
import { saveToken } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

const TIMEZONES = [
  { value: 'Asia/Kolkata', label: 'Asia/Kolkata (IST, UTC+5:30)' },
  { value: 'Asia/Dubai', label: 'Asia/Dubai (GST, UTC+4)' },
  { value: 'UTC', label: 'UTC' },
] as const

const signupSchema = z.object({
  full_name: z.string().min(2, 'Full name must be at least 2 characters'),
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
  clinic_name: z.string().min(2, 'Clinic name must be at least 2 characters'),
  twilio_number: z
    .string()
    .regex(
      /^whatsapp:\+[1-9]\d{6,14}$/,
      'Must match format: whatsapp:+91XXXXXXXXXX'
    ),
  timezone: z.enum(['Asia/Kolkata', 'Asia/Dubai', 'UTC'], {
    error: 'Please select a timezone',
  }),
})

type SignupValues = z.infer<typeof signupSchema>

export default function SignupPage() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)

  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<SignupValues>({
    resolver: zodResolver(signupSchema),
    defaultValues: {
      timezone: 'Asia/Kolkata',
    },
  })

  async function onSubmit(values: SignupValues) {
    setLoading(true)
    try {
      const { data } = await api.post<{ access_token: string }>('/api/auth/signup', values)
      saveToken(data.access_token)
      router.push('/onboarding')
    } catch (err: unknown) {
      const errData = (err as any)?.response?.data;
      let message = 'Signup failed. Please try again.';
      if (errData?.detail) {
        if (typeof errData.detail === 'string') {
          message = errData.detail;
        } else if (Array.isArray(errData.detail)) {
          message = errData.detail[0]?.msg || message;
        }
      }
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Create your account</h1>
        <p className="text-sm text-muted-foreground">Get started with ClinicAI in minutes</p>
      </div>

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        {/* Full Name */}
        <div className="space-y-1.5">
          <Label htmlFor="full_name">Full Name</Label>
          <Input
            id="full_name"
            type="text"
            placeholder="Dr. Jane Smith"
            autoComplete="name"
            aria-invalid={!!errors.full_name}
            {...register('full_name')}
          />
          {errors.full_name && (
            <p className="text-xs text-destructive">{errors.full_name.message}</p>
          )}
        </div>

        {/* Email */}
        <div className="space-y-1.5">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            placeholder="you@example.com"
            autoComplete="email"
            aria-invalid={!!errors.email}
            {...register('email')}
          />
          {errors.email && (
            <p className="text-xs text-destructive">{errors.email.message}</p>
          )}
        </div>

        {/* Password */}
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            placeholder="••••••••"
            autoComplete="new-password"
            aria-invalid={!!errors.password}
            {...register('password')}
          />
          {errors.password && (
            <p className="text-xs text-destructive">{errors.password.message}</p>
          )}
        </div>

        {/* Clinic Name */}
        <div className="space-y-1.5">
          <Label htmlFor="clinic_name">Clinic Name</Label>
          <Input
            id="clinic_name"
            type="text"
            placeholder="Sunrise Medical Centre"
            aria-invalid={!!errors.clinic_name}
            {...register('clinic_name')}
          />
          {errors.clinic_name && (
            <p className="text-xs text-destructive">{errors.clinic_name.message}</p>
          )}
        </div>

        {/* Twilio WhatsApp Number */}
        <div className="space-y-1.5">
          <Label htmlFor="twilio_number">Twilio WhatsApp Number</Label>
          <Input
            id="twilio_number"
            type="text"
            placeholder="whatsapp:+91XXXXXXXXXX"
            aria-invalid={!!errors.twilio_number}
            {...register('twilio_number')}
          />
          <p className="text-xs text-muted-foreground">
            The number patients will WhatsApp, format: whatsapp:+91XXXXXXXXXX
          </p>
          {errors.twilio_number && (
            <p className="text-xs text-destructive">{errors.twilio_number.message}</p>
          )}
        </div>

        {/* Timezone */}
        <div className="space-y-1.5">
          <Label htmlFor="timezone">Timezone</Label>
          <Controller
            name="timezone"
            control={control}
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger id="timezone" className="w-full" aria-invalid={!!errors.timezone}>
                  <SelectValue placeholder="Select timezone" />
                </SelectTrigger>
                <SelectContent>
                  {TIMEZONES.map((tz) => (
                    <SelectItem key={tz.value} value={tz.value}>
                      {tz.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
          {errors.timezone && (
            <p className="text-xs text-destructive">{errors.timezone.message}</p>
          )}
        </div>

        <Button type="submit" className="w-full" size="lg" disabled={loading}>
          {loading ? (
            <>
              <Loader2 className="size-4 animate-spin" />
              Creating account…
            </>
          ) : (
            'Create account'
          )}
        </Button>
      </form>

      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{' '}
        <Link href="/auth/login" className="font-medium text-primary hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  )
}
