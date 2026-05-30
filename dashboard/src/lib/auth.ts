const TOKEN_KEY = 'clinicai_token'

export const saveToken = (token: string): void => {
  if (typeof window !== 'undefined') localStorage.setItem(TOKEN_KEY, token)
}

export const getToken = (): string | null =>
  typeof window !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null

export const removeToken = (): void => {
  if (typeof window !== 'undefined') localStorage.removeItem(TOKEN_KEY)
}

export const isAuthenticated = (): boolean => !!getToken()

/** @deprecated Use getToken() */
export const getAuthToken = getToken
