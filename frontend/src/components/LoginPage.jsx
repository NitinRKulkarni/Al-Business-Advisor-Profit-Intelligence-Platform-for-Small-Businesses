import React, { useState } from 'react'
import { useAuth } from '../context/AuthContext'

export default function LoginPage() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [rememberMe, setRememberMe] = useState(true)
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setErrorMsg('')

    if (!username.trim() || !password.trim()) {
      setErrorMsg('Please enter both User ID and Password.')
      return
    }

    try {
      setIsLoading(true)
      await login(username.trim(), password.trim(), rememberMe)
    } catch (err) {
      setErrorMsg(err.message || 'Invalid credentials. Please check your User ID and Password.')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="sanskriti-login-wrapper">
      {/* Background ambient glows */}
      <div className="sanskriti-glow glow-1" />
      <div className="sanskriti-glow glow-2" />
      <div className="sanskriti-glow glow-3" />

      <div className="sanskriti-login-card">
        {/* Header Branding */}
        <div className="sanskriti-brand-header">
          <div className="vyapaar-logo-container">
            <img src="/vyapaar-mitra-logo.png" alt="Vyapaar Mitra Logo" className="vyapaar-login-logo" />
          </div>

          <span className="sanskriti-eyebrow">Team Sanskriti Presents</span>
          <h1 className="sanskriti-title">
            Vyapaar <span>Mitra</span>
          </h1>
          <p className="sanskriti-desc">
            Simplifying Business, Multiplying Growth.
          </p>
        </div>

        {/* Error Alert */}
        {errorMsg && (
          <div className="sanskriti-error-alert">
            <svg className="sanskriti-alert-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="sanskriti-form">
          <div className="sanskriti-field-group">
            <label className="sanskriti-label">User ID / Account ID</label>
            <div className="sanskriti-input-wrapper">
              <span className="sanskriti-input-icon">
                <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
              </span>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter your User ID"
                required
                autoFocus
                disabled={isLoading}
                className="sanskriti-input"
              />
            </div>
          </div>

          <div className="sanskriti-field-group">
            <label className="sanskriti-label">Password</label>
            <div className="sanskriti-input-wrapper">
              <span className="sanskriti-input-icon">
                <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                </svg>
              </span>
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••••"
                required
                disabled={isLoading}
                className="sanskriti-input"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="sanskriti-toggle-pw"
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? (
                  <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18" />
                  </svg>
                ) : (
                  <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          <div className="sanskriti-options-row">
            <label className="sanskriti-remember-label">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="sanskriti-checkbox"
              />
              <span>Remember session</span>
            </label>
            <span className="sanskriti-security-badge">Protected by Omni-CFO Shield</span>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="sanskriti-submit-btn"
          >
            {isLoading ? (
              <>
                <span className="sanskriti-spinner" />
                <span>Verifying Credentials...</span>
              </>
            ) : (
              <>
                <span>Sign In to Platform</span>
                <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
              </>
            )}
          </button>
        </form>

        {/* Footer */}
        <div className="sanskriti-card-footer">
          <p>
            Authorized credentials required · Configured in <code>.env</code>
          </p>
        </div>
      </div>
    </div>
  )
}
