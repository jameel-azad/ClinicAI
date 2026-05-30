export const saveToken = (token: string) => localStorage.setItem('clinicai_token', token)
export const getToken = () => typeof window !== 'undefined' ? localStorage.getItem('clinicai_token') : null
export const removeToken = () => localStorage.removeItem('clinicai_token')
export const isAuthenticated = () => !!getToken()
