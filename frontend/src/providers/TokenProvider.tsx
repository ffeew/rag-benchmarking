import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

const STORAGE_KEY = 'rag-token'

type TokenContextValue = {
  token: string
  isAuthed: boolean
  setToken: (token: string) => void
  clearToken: () => void
}

const TokenContext = createContext<TokenContextValue | null>(null)

function readInitial(): string {
  if (typeof window === 'undefined') return ''
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

export function TokenProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string>(readInitial)

  useEffect(() => {
    try {
      if (token) window.sessionStorage.setItem(STORAGE_KEY, token)
      else window.sessionStorage.removeItem(STORAGE_KEY)
    } catch {
      /* ignore */
    }
  }, [token])

  const setToken = useCallback((next: string) => setTokenState(next.trim()), [])
  const clearToken = useCallback(() => setTokenState(''), [])

  const value = useMemo<TokenContextValue>(
    () => ({ token, isAuthed: token.length > 0, setToken, clearToken }),
    [token, setToken, clearToken],
  )

  return <TokenContext.Provider value={value}>{children}</TokenContext.Provider>
}

export function useToken() {
  const ctx = useContext(TokenContext)
  if (!ctx) throw new Error('useToken must be used within TokenProvider')
  return ctx
}
