import React from 'react'

export default function EmptyState({
  icon = '📁',
  title = 'No Data Available',
  description = 'There are currently no records matching this criteria.',
  actionLabel,
  onAction,
  className = '',
  style = {},
}) {
  return (
    <div
      className={`empty-state-container ${className}`}
      style={{
        padding: '36px 20px',
        textAlign: 'center',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f8fafc',
        borderRadius: '12px',
        border: '1px dashed #cbd5e1',
        margin: '12px 0',
        ...style,
      }}
    >
      <div
        style={{
          fontSize: '32px',
          marginBottom: '10px',
          width: '56px',
          height: '56px',
          borderRadius: '50%',
          background: '#eef2ff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {icon}
      </div>
      <h3 style={{ fontSize: '15px', fontWeight: '700', color: '#1e293b', margin: '0 0 6px' }}>{title}</h3>
      <p style={{ fontSize: '13px', color: '#64748b', maxWidth: '420px', margin: '0 0 16px', lineHeight: '1.5' }}>
        {description}
      </p>
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={onAction}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '7px 16px',
            borderRadius: '8px',
            background: '#4f46e5',
            color: '#ffffff',
            fontSize: '13px',
            fontWeight: '600',
            border: 'none',
            cursor: 'pointer',
            boxShadow: '0 1px 2px rgba(79, 70, 229, 0.2)',
          }}
        >
          {actionLabel}
        </button>
      )}
    </div>
  )
}
