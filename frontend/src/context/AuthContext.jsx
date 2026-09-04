import React, { createContext, useContext, useState, useEffect } from 'react'
import { loginUser, verifySession } from '../services/api'

const AuthContext = createContext(null)

const AUTH_STORAGE_KEY = 'sanskriti_auth_session'

export function AuthProvider({ children }) {
  const [authState, setAuthState] = useState(() => {
    try {
      const saved = sessionStorage.getItem(AUTH_STORAGE_KEY) || localStorage.getItem(AUTH_STORAGE_KEY)
      if (saved) {
        const parsed = JSON.parse(saved)
        return {
          isAuthenticated: Boolean(parsed.token),
          token: parsed.token || null,
          username: parsed.username || '',
          brandName: parsed.brandName || "Team Sanskriti's Vyapaar Mitra",
          isLoading: false,
        }
      }
    } catch {
      // Fallback
    }
    return {
      isAuthenticated: false,
      token: null,
      username: '',
      brandName: "Team Sanskriti's Vyapaar Mitra",
      isLoading: false,
    }
  })

  const login = async (username, password, rememberMe = true) => {
    const data = await loginUser(username, password)
    const sessionData = {
      token: data.token,
      username: data.username,
      brandName: data.brandName || "Team Sanskriti's Vyapaar Mitra",
    }

    if (rememberMe) {
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(sessionData))
    } else {
      sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(sessionData))
    }

    setAuthState({
      isAuthenticated: true,
      token: data.token,
      username: data.username,
      brandName: data.brandName || "Team Sanskriti's Vyapaar Mitra",
      isLoading: false,
    })

    return data
  }

  const logout = () => {
    localStorage.removeItem(AUTH_STORAGE_KEY)
    sessionStorage.removeItem(AUTH_STORAGE_KEY)
    setAuthState({
      isAuthenticated: false,
      token: null,
      username: '',
      brandName: "Team Sanskriti's Vyapaar Mitra",
      isLoading: false,
    })
  }

  return (
    <AuthContext.Provider value={{ ...authState, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
