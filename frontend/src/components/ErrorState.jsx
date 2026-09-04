import React, { useState } from 'react'

export default function ErrorState({
  title = 'Unable to Load Data',
  message = 'A network or server error occurred while contacting the OmniCFO backend.',
  onRetry,
  className = '',
  style = {},
}) {
  const [isRetrying, setIsRetrying] = useState(false)

  const handleRetry = async () => {
    if (!onRetry) return
    setIsRetrying(true)
    try {
      await onRetry()
    } finally {
      setIsRetrying(false)
    }
  }

  return (
    <div
      className={`error-state-card ${className}`}
      style={{
        padding: '24px 20px',
        borderRadius: '12px',
        border: '1px solid #fecaca',
        background: '#fff5f5',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        textAlign: 'center',
        margin: '12px 0',
        ...style,
      }}
    >
      <div
        style={{
          width: '42px',
          height: '42px',
          borderRadius: '50%',
          background: '#fee2e2',
          color: '#dc2626',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '20px',
          marginBottom: '10px',
        }}
      >
        ⚠️
      </div>
      <h4 style={{ margin: '0 0 4px', fontSize: '14px', fontWeight: '700', color: '#991b1b' }}>{title}</h4>
      <p style={{ margin: '0 0 14px', fontSize: '12px', color: '#7f1d1d', maxWidth: '440px', lineHeight: '1.4' }}>
        {message}
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={handleRetry}
          disabled={isRetrying}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '6px 16px',
            borderRadius: '8px',
            border: '1px solid #f87171',
            background: '#ffffff',
            color: '#b91c1c',
            fontSize: '12px',
            fontWeight: '600',
            cursor: isRetrying ? 'not-allowed' : 'pointer',
            boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
          }}
        >
          {isRetrying ? '⟳ Retrying...' : '↻ Retry'}
        </button>
      )}
    </div>
  )
}
