import React from 'react'

export function Shimmer({ width = '100%', height = '16px', borderRadius = '4px', className = '', style = {} }) {
  return (
    <div
      className={`skeleton-shimmer ${className}`}
      style={{
        width,
        height,
        borderRadius,
        ...style,
      }}
    />
  )
}

export function KpiSkeletonGrid() {
  return (
    <div className="kpi-grid">
      {[1, 2, 3, 4].map((i) => (
        <article key={i} className="kpi-card skeleton-card">
          <div className="kpi-top" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Shimmer width="45%" height="14px" />
            <Shimmer width="32px" height="32px" borderRadius="8px" />
          </div>
          <div style={{ margin: '14px 0 10px' }}>
            <Shimmer width="70%" height="28px" borderRadius="6px" />
          </div>
          <div className="kpi-footer" style={{ borderTop: '1px solid #f1f5f9', paddingTop: '8px' }}>
            <Shimmer width="80%" height="12px" />
          </div>
        </article>
      ))}
    </div>
  )
}

export function TableRowSkeleton({ rows = 4, cols = 5 }) {
  return (
    <tbody>
      {Array.from({ length: rows }).map((_, r) => (
        <tr key={r} className="skeleton-row">
          {Array.from({ length: cols }).map((_, c) => (
            <td key={c}>
              <Shimmer width={c === 0 ? '75%' : c === 1 ? '50%' : '65%'} height="15px" />
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  )
}

export function ChartSkeleton() {
  return (
    <div className="chart-card skeleton-chart-card" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '20px' }}>
        <div>
          <Shimmer width="220px" height="20px" style={{ marginBottom: '8px' }} />
          <Shimmer width="320px" height="14px" />
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <Shimmer width="120px" height="32px" borderRadius="8px" />
          <Shimmer width="160px" height="32px" borderRadius="8px" />
        </div>
      </div>
      <div style={{ height: '240px', width: '100%', position: 'relative', overflow: 'hidden', borderRadius: '12px' }}>
        <Shimmer width="100%" height="100%" borderRadius="12px" />
      </div>
    </div>
  )
}

export function InsightSkeleton() {
  return (
    <div className="insights-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '16px' }}>
      {[1, 2, 3].map((i) => (
        <article key={i} className="insight-card skeleton-card" style={{ padding: '20px' }}>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
            <Shimmer width="36px" height="36px" borderRadius="10px" />
            <div style={{ flex: 1 }}>
              <Shimmer width="30%" height="12px" style={{ marginBottom: '8px' }} />
              <Shimmer width="60%" height="18px" style={{ marginBottom: '8px' }} />
              <Shimmer width="90%" height="14px" />
            </div>
          </div>
        </article>
      ))}
    </div>
  )
}
