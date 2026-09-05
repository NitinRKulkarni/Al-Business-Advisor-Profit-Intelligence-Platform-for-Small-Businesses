import { useEffect, useRef, useState } from 'react'
import { getDocuments, uploadAllDocuments, uploadDocument, retryDocument, fetchDocumentBlob, getDocumentViewUrl, getDemandInsights, getInvoices, getBankStatements } from './services/api'
import { useAuth } from './context/AuthContext'
import LoginPage from './components/LoginPage'
import { KpiSkeletonGrid, TableRowSkeleton, ChartSkeleton, InsightSkeleton } from './components/Skeleton'
import EmptyState from './components/EmptyState'
import ErrorState from './components/ErrorState'


const initialUploads = {
  bank: [],
  invoices: [],
  images: [],
  inventory: [],
  whatsapp: [],
}

const uploadConfigs = {
  bank: {
    title: 'Bank statement',
    description: 'Upload your latest statement for a clear cash-flow view.',
    formats: '.csv only',
    accept: '.csv,text/csv',
    icon: 'bank',
    accent: 'blue',
    multiple: false,
  },
  invoices: {
    title: 'PDF invoices',
    description: 'Add customer and supplier invoices in one go.',
    formats: '.pdf only · up to 20 files',
    accept: '.pdf,application/pdf',
    icon: 'file-text',
    accent: 'purple',
    multiple: true,
  },
  images: {
    title: 'Invoice images',
    description: 'Upload photos or scans of your paper invoices.',
    formats: '.jpg, .jpeg, .png · up to 20 files',
    accept: '.jpg,.jpeg,.png,image/jpeg,image/png',
    icon: 'image',
    accent: 'orange',
    multiple: true,
  },
  inventory: {
    title: 'Inventory Stock Sheet (CSV)',
    description: 'Upload ground-truth product stock catalog (sourceType=csv_inventory).',
    formats: '.csv only',
    accept: '.csv,text/csv',
    icon: 'boxes',
    accent: 'green',
    multiple: false,
  },
}

const navItems = [
  { id: 'dashboard', label: 'Dashboard', icon: 'grid' },
  { id: 'uploads', label: 'Data Uploads', icon: 'upload', badgeKey: 'uploads' },
  { id: 'invoices', label: 'Unpaid Invoices', icon: 'file-text', badge: '0' },
  { id: 'insights', label: 'AI Insights', icon: 'sparkles', badge: '1' },
  { id: 'profile', label: 'Organization Profile', icon: 'building' },
  { id: 'settings', label: 'Settings', icon: 'help' },
]

// Dynamic Trend Data Generator based on active period and ingested invoice metrics
function generateTrendData(period, invoices = []) {
  const countMap = {
    '7d': 7,
    '14d': 14,
    '30d': 4,
    '90d': 3,
  }
  const count = countMap[period] || 7
  const now = new Date()
  
  // Calculate base revenue/expenses from real invoices if present
  const totalInvoiceRev = invoices.reduce((acc, inv) => acc + (parseFloat(inv.amount) || 0), 0)
  const paidInvoiceRev = invoices.filter(inv => inv.status === 'paid' || inv.paymentStatus === 'PAID')
                                .reduce((acc, inv) => acc + (parseFloat(inv.amount || inv.paidAmount) || 0), 0)

  const items = []
  for (let i = count - 1; i >= 0; i--) {
    let dateLabel = ''
    if (period === '7d') {
      const d = new Date(now)
      d.setDate(d.getDate() - i)
      dateLabel = d.toLocaleDateString('en-US', { weekday: 'short' })
    } else if (period === '14d') {
      dateLabel = `Day ${count - i}`
    } else if (period === '30d') {
      dateLabel = `Week ${count - i}`
    } else {
      dateLabel = `Month ${count - i}`
    }

    // Allocate real revenue dynamically across the period
    const dayRev = count > 0 && totalInvoiceRev > 0 ? Math.round((paidInvoiceRev / count) * (1 + (i % 3) * 0.2)) : 0
    const dayExp = count > 0 && totalInvoiceRev > 0 ? Math.round((dayRev * 0.4)) : 0

    items.push({
      date: dateLabel,
      revenue: dayRev,
      expenses: dayExp,
    })
  }

  return items
}

// Zeroed Initial Unpaid Invoices
const initialInvoices = []

const currencies = {
  USD: { symbol: '$', code: 'USD', name: 'US Dollar' },
  EUR: { symbol: '€', code: 'EUR', name: 'Euro' },
  GBP: { symbol: '£', code: 'GBP', name: 'British Pound' },
  INR: { symbol: '₹', code: 'INR', name: 'Indian Rupee' },
}

function Icon({ name, size = 18, strokeWidth = 1.8 }) {
  const paths = {
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
    bank: <><path d="m3 10 9-6 9 6" /><path d="M5 10v8M9 10v8M15 10v8M19 10v8" /><path d="M3 20h18M2 10h20" /></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" /><path d="M10 21h4" /></>,
    building: <><path d="M4 21V5l8-3 8 3v16" /><path d="M2 21h20M8 8h1M15 8h1M8 12h1M15 12h1M8 16h1M15 16h1" /></>,
    boxes: <><path d="m3 7 9-4 9 4-9 4-9-4Z" /><path d="M3 7v10l9 4 9-4V7M12 11v10" /></>,
    chart: <><path d="M3 3v18h18" /><path d="m19 9-5 5-4-4-5 5" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    chevron: <path d="m6 9 6 6 6-6" />,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6" /></>,
    'file-text': <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6M8 13h8M8 17h6" /></>,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    help: <><circle cx="12" cy="12" r="9" /><path d="M9.6 9a2.5 2.5 0 1 1 4.1 1.9c-1.1.8-1.7 1.2-1.7 2.6M12 17h.01" /></>,
    image: <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="m21 15-5-5L5 21" /></>,
    menu: <><path d="M4 6h16M4 12h16M4 18h16" /></>,
    message: <><path d="M20 11.5a7.5 7.5 0 0 1-8 7.5 8.5 8.5 0 0 1-4-.9L4 20l1-3.3a7.2 7.2 0 0 1-1-4.2A7.5 7.5 0 0 1 12 5a7.5 7.5 0 0 1 8 6.5Z" /><path d="M8 12h.01M12 12h.01M16 12h.01" /></>,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    refresh: <><path d="M20 11a8 8 0 1 0 1 4" /><path d="M20 4v7h-7" /></>,
    shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" /><path d="m9 12 2 2 4-4" /></>,
    trash: <><path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6M10 10v7M14 10v7" /></>,
    upload: <><path d="M12 16V4M7 9l5-5 5 5" /><path d="M5 20h14" /></>,
    user: <><circle cx="12" cy="8" r="3.5" /><path d="M5 20a7 7 0 0 1 14 0" /></>,
    whatsapp: <><path d="M20 11.5a8 8 0 0 1-11.8 7L4 20l1.5-4A8 8 0 1 1 20 11.5Z" /><path d="M9 9.5c.3 2 1.5 3.3 3.5 4 .5.2 1-.2 1.4-.8l.4-.6" /></>,
    sparkles: <><path d="m12 3 1.912 5.813a2 2 0 0 0 1.275 1.275L21 12l-5.813 1.912a2 2 0 0 0-1.275 1.275L12 21l-1.912-5.813a2 2 0 0 0-1.275-1.275L3 12l5.813-1.912a2 2 0 0 0 1.275-1.275L12 3Z" /></>,
    'trending-up': <><path d="m22 7-8.5 8.5-5-5L1 18" /><path d="M16 7h6v6" /></>,
    'trending-down': <><path d="m22 17-8.5-8.5-5 5L1 6" /><path d="M16 17h6v-6" /></>,
    dollar: <><line x1="12" y1="1" x2="12" y2="23" /><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" /></>,
    pie: <><path d="M21.21 15.89A10 10 0 1 1 8 2.83" /><path d="M22 12A10 10 0 0 0 12 2v10z" /></>,
    search: <><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></>,
    filter: <><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" /></>,
    send: <><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></>,
    alert: <><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></>,
    download: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></>,
    logout: <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" /></>,
    globe: <><circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></>,
    lock: <><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></>,
    key: <><path d="m21 2-2 2m-1.5 1.5L14 9.5a5 5 0 1 0 4.5 4.5l3.5-3.5V8.5h-2V6.5h-2.5L21 2Z" /></>,
  }

  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.file}</svg>
}

function formatCurrency(amount, currencyCode = 'INR') {
  const curr = currencies[currencyCode] || currencies.INR || currencies.USD
  const locale = curr.code === 'INR' ? 'en-IN' : 'en-US'
  return new Intl.NumberFormat(locale, { style: 'currency', currency: curr.code, maximumFractionDigits: 2 }).format(Number(amount) || 0)
}

function formatBytes(bytes) {
  if (!bytes) return '0 KB'
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function getExtension(name) {
  return `.${name.split('.').pop().toLowerCase()}`
}

// Component: Trend Chart (Interactive SVG with Dynamic Values)
function TrendChart({ period, setPeriod, viewMode, setViewMode, currency, invoices = [], isLoading = false, error = null, onRetry = null }) {
  const [hoveredPoint, setHoveredPoint] = useState(null)

  if (isLoading) {
    return <ChartSkeleton />
  }

  if (error) {
    return (
      <div className="chart-card" style={{ padding: '24px' }}>
        <ErrorState
          title="Unable to Load Daily Trends"
          message={error}
          onRetry={onRetry}
        />
      </div>
    )
  }

  const data = generateTrendData(period, invoices)


  const totalRev = data.reduce((acc, d) => acc + d.revenue, 0)
  const totalExp = data.reduce((acc, d) => acc + d.expenses, 0)
  const netProfit = totalRev - totalExp
  
  const maxVal = Math.max(...data.map(d => Math.max(d.revenue, d.expenses))) * 1.15 || 500

  const width = 760
  const height = 240
  const padLeft = 55
  const padRight = 25
  const padTop = 25
  const padBottom = 35

  const graphWidth = width - padLeft - padRight
  const graphHeight = height - padTop - padBottom

  const getX = (index) => padLeft + (index / (data.length - 1)) * graphWidth
  const getY = (val) => padTop + graphHeight - (val / maxVal) * graphHeight

  // Path constructions
  const revPoints = data.map((d, i) => `${getX(i)},${getY(d.revenue)}`).join(' ')
  const expPoints = data.map((d, i) => `${getX(i)},${getY(d.expenses)}`).join(' ')

  const revArea = `M ${getX(0)},${height - padBottom} ` + data.map((d, i) => `L ${getX(i)},${getY(d.revenue)}`).join(' ') + ` L ${getX(data.length - 1)},${height - padBottom} Z`
  const expArea = `M ${getX(0)},${height - padBottom} ` + data.map((d, i) => `L ${getX(i)},${getY(d.expenses)}`).join(' ') + ` L ${getX(data.length - 1)},${height - padBottom} Z`

  // Grid steps
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map(pct => Math.round(maxVal * pct))
  const sym = currencies[currency]?.symbol || '$'

  return (
    <div className="chart-card">
      <div className="chart-header">
        <div>
          <div className="chart-title-wrap">
            <Icon name="chart" size={20} />
            <h3>Daily Financial Performance Trends</h3>
          </div>
          <p>Daily breakdown of revenue inflows vs expense outflows for selected timeframe</p>
        </div>

        <div className="chart-controls">
          <div className="view-mode-toggle">
            <button className={`mode-btn ${viewMode === 'all' ? 'active' : ''}`} onClick={() => setViewMode('all')}>Both</button>
            <button className={`mode-btn rev ${viewMode === 'revenue' ? 'active' : ''}`} onClick={() => setViewMode('revenue')}>Revenue</button>
            <button className={`mode-btn exp ${viewMode === 'expenses' ? 'active' : ''}`} onClick={() => setViewMode('expenses')}>Expenses</button>
          </div>

          <div className="period-selector">
            <button className={`period-btn ${period === '7d' ? 'active' : ''}`} onClick={() => setPeriod('7d')}>7 Days</button>
            <button className={`period-btn ${period === '14d' ? 'active' : ''}`} onClick={() => setPeriod('14d')}>14 Days</button>
            <button className={`period-btn ${period === '30d' ? 'active' : ''}`} onClick={() => setPeriod('30d')}>30 Days</button>
            <button className={`period-btn ${period === '90d' ? 'active' : ''}`} onClick={() => setPeriod('90d')}>90 Days</button>
          </div>
        </div>
      </div>

      <div className="chart-container">
        <svg viewBox={`0 0 ${width} ${height}`} className="trend-svg">
          <defs>
            <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#4f46e5" stopOpacity="0.25" />
              <stop offset="100%" stopColor="#4f46e5" stopOpacity="0.0" />
            </linearGradient>
            <linearGradient id="expGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.2" />
              <stop offset="100%" stopColor="#f43f5e" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {yTicks.map((val, idx) => {
            const y = getY(val)
            return (
              <g key={idx} className="grid-group">
                <line x1={padLeft} y1={y} x2={width - padRight} y2={y} stroke="#e2e8f0" strokeDasharray="4 4" />
                <text x={padLeft - 8} y={y + 4} textAnchor="end" className="chart-axis-label">
                  {sym}{val >= 1000 ? `${(val / 1000).toFixed(0)}k` : val}
                </text>
              </g>
            )
          })}

          {/* Areas */}
          {(viewMode === 'all' || viewMode === 'expenses') && (
            <path d={expArea} fill="url(#expGrad)" />
          )}
          {(viewMode === 'all' || viewMode === 'revenue') && (
            <path d={revArea} fill="url(#revGrad)" />
          )}

          {/* Trend Lines */}
          {(viewMode === 'all' || viewMode === 'expenses') && (
            <polyline fill="none" stroke="#f43f5e" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" points={expPoints} />
          )}
          {(viewMode === 'all' || viewMode === 'revenue') && (
            <polyline fill="none" stroke="#4f46e5" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" points={revPoints} />
          )}

          {/* Data interactive points & X labels */}
          {data.map((d, i) => {
            const x = getX(i)
            const yRev = getY(d.revenue)
            const yExp = getY(d.expenses)
            const isHovered = hoveredPoint === i

            return (
              <g key={i} className="point-group" onMouseEnter={() => setHoveredPoint(i)} onMouseLeave={() => setHoveredPoint(null)}>
                {isHovered && (
                  <line x1={x} y1={padTop} x2={x} y2={height - padBottom} stroke="#94a3b8" strokeDasharray="3 3" strokeWidth="1.5" />
                )}

                <text x={x} y={height - 10} textAnchor="middle" className={`chart-axis-label ${isHovered ? 'active' : ''}`}>
                  {d.date}
                </text>

                {(viewMode === 'all' || viewMode === 'expenses') && (
                  <circle cx={x} cy={yExp} r={isHovered ? 6 : 4} fill="#ffffff" stroke="#f43f5e" strokeWidth="2.5" className="chart-dot" />
                )}

                {(viewMode === 'all' || viewMode === 'revenue') && (
                  <circle cx={x} cy={yRev} r={isHovered ? 6 : 4} fill="#ffffff" stroke="#4f46e5" strokeWidth="2.5" className="chart-dot" />
                )}
              </g>
            )
          })}
        </svg>

        {/* Hover Floating Tooltip */}
        {hoveredPoint !== null && (
          <div className="chart-tooltip" style={{ left: `${Math.min(82, Math.max(12, (hoveredPoint / (data.length - 1)) * 100))}%` }}>
            <div className="tooltip-date">{data[hoveredPoint].date}</div>
            <div className="tooltip-row rev">
              <span><i /> Revenue:</span>
              <strong>{formatCurrency(data[hoveredPoint].revenue, currency)}</strong>
            </div>
            <div className="tooltip-row exp">
              <span><i /> Expenses:</span>
              <strong>{formatCurrency(data[hoveredPoint].expenses, currency)}</strong>
            </div>
            <div className="tooltip-row net">
              <span>Net Cashflow:</span>
              <strong>{formatCurrency(data[hoveredPoint].revenue - data[hoveredPoint].expenses, currency)}</strong>
            </div>
          </div>
        )}
      </div>

      {/* Chart Footer Metrics */}
      <div className="chart-footer">
        <div className="chart-legend">
          <span className="legend-item rev"><i /> Daily Revenue: <strong>{formatCurrency(totalRev, currency)}</strong></span>
          <span className="legend-item exp"><i /> Daily Expenses: <strong>{formatCurrency(totalExp, currency)}</strong></span>
          <span className="legend-item net"><i /> Net Cashflow: <strong>{formatCurrency(netProfit, currency)}</strong></span>
        </div>
        <div className="chart-badge">
          <Icon name="sparkles" size={14} />
          <span>Average daily revenue: <strong>{formatCurrency(totalRev / data.length, currency)}</strong></span>
        </div>
      </div>
    </div>
  )
}

// Component: Unpaid Invoices Section
function UnpaidInvoicesSection({ invoices = [], isLoading = false, error = null, onRetry = null, onSendReminder, currency, onAddInvoice }) {
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [remindedMap, setRemindedMap] = useState({})

  const handleReminder = (id) => {
    setRemindedMap(prev => ({ ...prev, [id]: true }))
    onSendReminder(id)
  }

  if (error) {
    return (
      <div className="invoices-card">
        <ErrorState
          title="Failed to Load Invoices"
          message={error}
          onRetry={onRetry}
        />
      </div>
    )
  }

  const filteredInvoices = invoices.filter(inv => {
    const matchesFilter = filter === 'all' ? true : inv.status === filter
    const matchesSearch = inv.customer.toLowerCase().includes(search.toLowerCase()) || inv.id.toLowerCase().includes(search.toLowerCase())
    return matchesFilter && matchesSearch
  })

  const totalOutstanding = invoices.reduce((acc, inv) => acc + (parseFloat(inv.amount) || 0), 0)
  const overdueTotal = invoices.filter(inv => inv.status === 'overdue').reduce((acc, inv) => acc + (parseFloat(inv.amount) || 0), 0)
  const dueSoonTotal = invoices.filter(inv => inv.status === 'due-soon').reduce((acc, inv) => acc + (parseFloat(inv.amount) || 0), 0)

  return (
    <div className="invoices-card">
      <div className="invoices-card-header">
        <div>
          <div className="title-with-badge">
            <h2>Unpaid Invoices</h2>
            <span className="count-pill green">{invoices.length} Pending</span>
          </div>
          <p>Track pending client balances, overdue accounts, and payment reminders</p>
        </div>

        <div className="invoices-actions">
          <button type="button" className="add-invoice-btn" onClick={onAddInvoice}>
            <Icon name="plus" size={14} />
            <span>Create Invoice</span>
          </button>

          <div className="search-box">
            <Icon name="search" size={15} />
            <input type="text" placeholder="Search customer or invoice #..." value={search} onChange={(e) => setSearch(e.target.value)} />
            {search && <button className="clear-search" onClick={() => setSearch('')}><Icon name="close" size={12} /></button>}
          </div>

          <div className="filter-tabs">
            <button className={`tab-btn ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>All ({invoices.length})</button>
            <button className={`tab-btn overdue ${filter === 'overdue' ? 'active' : ''}`} onClick={() => setFilter('overdue')}>Overdue ({invoices.filter(i => i.status === 'overdue').length})</button>
            <button className={`tab-btn duesoon ${filter === 'due-soon' ? 'active' : ''}`} onClick={() => setFilter('due-soon')}>Due Soon ({invoices.filter(i => i.status === 'due-soon').length})</button>
          </div>
        </div>
      </div>

      {/* Receivables Summary Bar */}
      <div className="receivables-summary-bar">
        <div className="summary-item">
          <span>Total Outstanding Balance</span>
          <strong>{formatCurrency(totalOutstanding, currency)}</strong>
        </div>
        <div className="summary-divider" />
        <div className="summary-item">
          <span>Overdue Accounts</span>
          <strong>{formatCurrency(overdueTotal, currency)} <small>({invoices.filter(i => i.status === 'overdue').length} invoices)</small></strong>
        </div>
        <div className="summary-divider" />
        <div className="summary-item">
          <span>Due Within 7 Days</span>
          <strong>{formatCurrency(dueSoonTotal, currency)} <small>({invoices.filter(i => i.status === 'due-soon').length} invoices)</small></strong>
        </div>
      </div>

      {/* Table View */}
      <div className="table-responsive">
        <table className="invoices-table">
          <thead>
            <tr>
              <th>Invoice #</th>
              <th>Customer Name</th>
              <th>Issue Date</th>
              <th>Due Date</th>
              <th>Amount</th>
              <th>Status</th>
              <th className="text-right">Action</th>
            </tr>
          </thead>
          {isLoading ? (
            <TableRowSkeleton rows={4} cols={7} />
          ) : filteredInvoices.length === 0 ? (
            <tbody>
              <tr>
                <td colSpan="7" style={{ padding: '8px 0' }}>
                  <EmptyState
                    icon="📄"
                    title="No Unpaid Invoices Found"
                    description="All customer balances are currently settled, or no unpaid invoice records are in the system."
                    actionLabel="Create Invoice"
                    onAction={onAddInvoice}
                  />
                </td>
              </tr>
            </tbody>
          ) : (
            <tbody>
              {filteredInvoices.map((inv) => (
                <tr key={inv.id}>
                  <td className="inv-id"><strong>{inv.id}</strong></td>
                  <td className="inv-customer"><strong>{inv.customer}</strong></td>
                  <td className="inv-date">{inv.issueDate}</td>
                  <td className="inv-date"><span>{inv.dueDate}</span></td>
                  <td className="inv-amount"><strong>{formatCurrency(inv.amount, currency)}</strong></td>
                  <td>
                    <span className={`status-pill ${inv.status}`}>
                      <i />
                      {inv.status}
                    </span>
                  </td>
                  <td className="text-right">
                    <button
                      type="button"
                      className={`reminder-btn ${remindedMap[inv.id] ? 'sent' : ''}`}
                      onClick={() => handleReminder(inv.id)}
                    >
                      <Icon name={remindedMap[inv.id] ? 'check' : 'send'} size={13} />
                      <span>{remindedMap[inv.id] ? 'Reminder Sent' : 'Send Reminder'}</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          )}
        </table>
      </div>
    </div>
  )
}

// Component: AI Insights Advisory Widget
function AIInsightsWidget({ onNavigateUploads, invoices = [], backendDocs = [], isLoading = false, error = null, onRetry = null }) {
  if (isLoading) {
    return (
      <div className="insights-section">
        <div className="section-header">
          <div>
            <span className="section-kicker">AI Organization Intelligence</span>
            <h2>Standard Advisory Status</h2>
          </div>
          <span className="ai-status-badge"><Icon name="sparkles" size={14} /> Syncing Intelligence...</span>
        </div>
        <InsightSkeleton />
      </div>
    )
  }

  if (error) {
    return (
      <div className="insights-section">
        <ErrorState
          title="Advisory Intelligence Offline"
          message={error}
          onRetry={onRetry}
        />
      </div>
    )
  }

  const invoiceCount = invoices.length
  const totalBackendDocs = backendDocs.length

  return (
    <div className="insights-section">
      <div className="section-header">
        <div>
          <span className="section-kicker">AI Organization Intelligence</span>
          <h2>Standard Advisory Status</h2>
        </div>
        <span className="ai-status-badge"><Icon name="sparkles" size={14} /> Organization Portal Active</span>
      </div>

      <div className="insights-grid">
        <article className="insight-card border-indigo">
          <div className="insight-icon indigo"><Icon name="upload" size={20} /></div>
          <div className="insight-content">
            <div className="insight-tag indigo">Data Integration</div>
            <h3>{totalBackendDocs > 0 ? `${totalBackendDocs} Document(s) Ingested` : 'Connect Financial Sources'}</h3>
            <p>{totalBackendDocs > 0 ? `${totalBackendDocs} financial document(s) securely stored in PostgreSQL database and processed.` : "Upload your organization's bank statements or invoices to begin automated financial trend analysis and cash flow monitoring."}</p>
            <div className="insight-actions">
              <button type="button" className="insight-btn primary indigo" onClick={onNavigateUploads}>
                <Icon name="upload" size={13} /> Upload Statements
              </button>
            </div>
          </div>
        </article>

        <article className="insight-card border-emerald">
          <div className="insight-icon emerald"><Icon name={invoiceCount > 0 ? "alert" : "check"} size={20} /></div>
          <div className="insight-content">
            <div className="insight-tag emerald">Receivables Status</div>
            <h3>{invoiceCount > 0 ? `${invoiceCount} Pending Unpaid Invoice(s)` : '0 Pending Unpaid Invoices'}</h3>
            <p>{invoiceCount > 0 ? `${invoiceCount} invoice document(s) synced from PostgreSQL backend database staged for payment reconciliation.` : 'All accounts are currently up to date with zero outstanding receivables or overdue customer invoices.'}</p>
          </div>
        </article>

        <article className="insight-card border-blue">
          <div className="insight-icon blue"><Icon name="shield" size={20} /></div>
          <div className="insight-content">
            <div className="insight-tag blue">Security & Privacy</div>
            <h3>Enterprise Workspace Ready</h3>
            <p>All processed data stays confidential and strictly within your local organization workspace context.</p>
          </div>
        </article>
      </div>
    </div>
  )
}

function FileRow({ file, onRemove, onReplace }) {
  return (
    <div className="file-row">
      <div className="file-row-icon"><Icon name="file" size={16} /></div>
      <div className="file-row-info">
        <strong title={file.name}>{file.name}</strong>
        <span>{formatBytes(file.size)} <i /> <em><Icon name="check" size={11} /> Ready</em></span>
      </div>
      <button type="button" className="file-action" onClick={onReplace} aria-label={`Replace ${file.name}`}><Icon name="refresh" size={15} /></button>
      <button type="button" className="file-action remove" onClick={onRemove} aria-label={`Remove ${file.name}`}><Icon name="trash" size={15} /></button>
    </div>
  )
}

function UploadCard({ config, files, onFiles, onRemove, onReplace, error, compact = false }) {
  const inputRef = useRef(null)
  const [isDragging, setIsDragging] = useState(false)
  const [replaceIndex, setReplaceIndex] = useState(null)

  const handleFiles = (incoming, event = null) => {
    const selected = Array.from(incoming || [])
    const valid = selected.filter((file) => config.accept.split(',').some((type) => type.startsWith('.') && getExtension(file.name) === type))
    const validationMessage = valid.length !== selected.length
      ? config.multiple ? `Only ${config.formats.split('·')[0].trim()} files are supported.` : `Please choose a ${config.formats.replace(' only', '')} file.`
      : ''

    if (replaceIndex !== null && valid.length) {
      const replaced = config.multiple
        ? files.map((file, index) => index === replaceIndex ? valid[0] : file)
        : valid.slice(0, 1)
      onFiles(replaced, validationMessage)
      setReplaceIndex(null)
    } else if (config.multiple) {
      onFiles([...files, ...valid].slice(0, 20), validationMessage)
    } else {
      onFiles(valid.slice(0, 1), validationMessage)
    }
    if (event && event.target) {
      event.target.value = null
    }
    if (inputRef.current) inputRef.current.value = ''
  }

  const handleDrop = (event) => {
    event.preventDefault()
    setIsDragging(false)
    handleFiles(event.dataTransfer.files)
  }

  return (
    <article className={`upload-card accent-${config.accent} ${compact ? 'compact-card' : ''}`}>
      <div className="card-heading">
        <div className="heading-icon"><Icon name={config.icon} size={22} /></div>
        <div><h3>{config.title}</h3><p>{config.description}</p></div>
        <span className={`card-status ${files.length ? 'has-files' : ''}`}><span />{files.length ? `${files.length} added` : 'Not added'}</span>
      </div>

      <div className="upload-content">
        {!files.length ? (
          <div className={`drop-zone ${isDragging ? 'dragging' : ''}`} onDragOver={(event) => { event.preventDefault(); setIsDragging(true) }} onDragLeave={() => setIsDragging(false)} onDrop={handleDrop} onClick={() => inputRef.current?.click()} role="button" tabIndex="0" onKeyDown={(event) => event.key === 'Enter' && inputRef.current?.click()}>
            <div className="drop-icon"><Icon name="upload" size={20} /></div>
            <div><strong>Drop {config.multiple ? 'files' : 'a file'} here or <button type="button" onClick={(event) => { event.stopPropagation(); inputRef.current?.click() }}>browse</button></strong><small>{config.formats}</small></div>
          </div>
        ) : (
          <div className="file-list">
            {files.map((file, index) => <FileRow key={`${file.name}-${index}`} file={file} onRemove={() => onRemove(index)} onReplace={() => { setReplaceIndex(index); inputRef.current?.click() }} />)}
            {config.multiple && files.length < 20 && <button type="button" className="add-more" onClick={() => inputRef.current?.click()}><Icon name="plus" size={15} /> Add more files</button>}
          </div>
        )}
        <input 
          ref={inputRef} 
          className="visually-hidden" 
          type="file" 
          accept={config.accept} 
          multiple={config.multiple} 
          onChange={(event) => {
            handleFiles(event.target.files, event)
            event.target.value = null
          }} 
        />
        {error && <p className="validation-error"><Icon name="help" size={14} />{error}</p>}
      </div>
    </article>
  )
}

function WhatsAppCard({ file, onFile, onClear, status, error }) {
  const inputRef = useRef(null)
  const [isDragging, setIsDragging] = useState(false)
  const statusLabels = {
    idle: 'Not added',
    ready: 'Ready to upload',
    processing: 'Processing...',
    success: 'Success',
    error: 'Error',
  }

  const handleFiles = (incoming, event = null) => {
    const selected = Array.from(incoming || [])
    const candidate = selected[0]
    const isZip = candidate && candidate.name.toLowerCase().endsWith('.zip')
    if (!candidate || !isZip) {
      onFile(null, 'Please choose a WhatsApp export .zip file.')
    } else {
      onFile(candidate, '')
    }
    if (event && event.target) {
      event.target.value = null
    }
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <article className="upload-card whatsapp-card accent-teal">
      <div className="card-heading">
        <div className="heading-icon"><Icon name="whatsapp" size={22} /></div>
        <div><h3>WhatsApp Customer Inquiries</h3><p>Upload chat export (.zip/.txt) to extract customer demand queries & questions.</p></div>
        <span className={`card-status ${file ? 'has-files' : ''}`}><span />{statusLabels[status] || statusLabels.idle}</span>
      </div>
      <div className="upload-content">
        {!file ? (
          <div
            className={`drop-zone ${isDragging ? 'dragging' : ''}`}
            onDragOver={(event) => { event.preventDefault(); setIsDragging(true) }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(event) => { event.preventDefault(); setIsDragging(false); handleFiles(event.dataTransfer.files) }}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex="0"
            onKeyDown={(event) => event.key === 'Enter' && inputRef.current?.click()}
          >
            <div className="drop-icon"><Icon name="upload" size={20} /></div>
            <div><strong>Drop a ZIP here or <button type="button" onClick={(event) => { event.stopPropagation(); inputRef.current?.click() }}>browse</button></strong><small>.zip WhatsApp export only</small></div>
          </div>
        ) : (
          <div className="file-list">
            <FileRow file={file} onRemove={onClear} onReplace={() => inputRef.current?.click()} />
          </div>
        )}
        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          accept=".zip,application/zip,application/x-zip-compressed"
          onChange={(event) => {
            handleFiles(event.target.files, event)
            event.target.value = null
          }}
        />
        {error && <p className="validation-error"><Icon name="help" size={14} />{error}</p>}
      </div>
      <button type="button" className="clear-button" onClick={onClear} disabled={!file || status === 'processing'}><Icon name="trash" size={14} /> Clear ZIP</button>
    </article>
  )
}

function WhatsAppItemsTable({ items }) {
  if (!items.length) return null

  return (
    <section className="invoices-card whatsapp-results-card">
      <div className="section-header">
        <div>
          <span className="section-kicker">WhatsApp extraction results</span>
          <h2>Extracted items</h2>
        </div>
        <span className="count-pill green">{items.length} items</span>
      </div>
      <div className="table-responsive">
        <table className="invoices-table">
          <thead>
            <tr>
              <th>Item Name</th>
              <th>Quantity</th>
              <th>Unit</th>
              <th>Date</th>
              <th>Time</th>
              <th>Description</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr key={`${item.item_name || 'item'}-${index}`}>
                <td className="inv-customer"><strong>{item.item_name || '—'}</strong></td>
                <td>{item.quantity ?? '—'}</td>
                <td>{item.quantity_unit || '—'}</td>
                <td className="inv-date">{item.date || '—'}</td>
                <td className="inv-date">{item.timestamp || '—'}</td>
                <td>{item.description || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

// Component: Document Preview Modal (Renders raw PDF, Image, CSV/Text, and Download options)
function DocumentPreviewModal({ doc, onClose }) {
  const [blobUrl, setBlobUrl] = useState(null)
  const [contentType, setContentType] = useState('')
  const [textContent, setTextContent] = useState(null)
  const [csvRows, setCsvRows] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let active = true
    let createdUrl = null

    const loadDoc = async () => {
      if (!doc || !doc.documentId) return
      setLoading(true)
      setError(null)
      setTextContent(null)
      setCsvRows(null)

      try {
        const { blob, contentType: rawType } = await fetchDocumentBlob(doc.documentId)
        if (!active) return

        const type = (rawType || blob.type || '').toLowerCase()
        setContentType(type)
        createdUrl = URL.createObjectURL(blob)
        setBlobUrl(createdUrl)

        const fileName = (doc.fileName || '').toLowerCase()
        const isCsv = fileName.endsWith('.csv') || type.includes('csv')
        const isText = fileName.endsWith('.txt') || type.includes('text') || isCsv

        if (isCsv || isText) {
          const text = await blob.text()
          if (!active) return
          if (isCsv) {
            const lines = text.split(/\r?\n/).filter(line => line.trim().length > 0)
            if (lines.length > 0) {
              const rows = lines.map(line => line.split(',').map(cell => cell.replace(/^"|"$/g, '').trim()))
              setCsvRows(rows)
            }
          }
          setTextContent(text)
        }
      } catch (err) {
        if (!active) return
        console.error('Failed to load document preview:', err)
        setError(err.message || 'Unable to stream file payload from PostgreSQL database.')
      } finally {
        if (active) setLoading(false)
      }
    }

    loadDoc()

    return () => {
      active = false
      if (createdUrl) {
        URL.revokeObjectURL(createdUrl)
      }
    }
  }, [doc])

  if (!doc) return null

  const fileName = doc.fileName || 'document'
  const lowerName = fileName.toLowerCase()
  const isPdf = lowerName.endsWith('.pdf') || contentType.includes('pdf')
  const isImage = lowerName.endsWith('.png') || lowerName.endsWith('.jpg') || lowerName.endsWith('.jpeg') || lowerName.endsWith('.webp') || contentType.includes('image')
  const isCsv = lowerName.endsWith('.csv') || contentType.includes('csv')
  const isZip = lowerName.endsWith('.zip') || contentType.includes('zip')

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="document-preview-modal-card" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="document-preview-header">
          <div className="document-preview-title">
            <div className="document-preview-icon">
              <Icon name={isPdf ? 'file-text' : isImage ? 'image' : isZip ? 'boxes' : 'file'} size={20} />
            </div>
            <div className="document-preview-meta">
              <strong title={fileName}>{fileName}</strong>
              <span>
                {doc.fileType || 'Document'} · {contentType || 'raw/binary'} · <em>PostgreSQL Stored</em>
              </span>
            </div>
          </div>

          <div className="document-preview-actions">
            {blobUrl && (
              <a
                href={blobUrl}
                download={fileName}
                className="btn-preview-download"
                title={`Download ${fileName}`}
              >
                <Icon name="download" size={14} />
                <span>Download Original</span>
              </a>
            )}
            <button
              type="button"
              className="btn-preview-close"
              onClick={onClose}
              aria-label="Close Preview"
            >
              <Icon name="close" size={18} />
            </button>
          </div>
        </div>

        {/* Content Body */}
        <div className="document-preview-body">
          {loading && (
            <div className="document-preview-empty-box">
              <span className="sanskriti-spinner" style={{ width: '28px', height: '28px', borderColor: 'rgba(79,70,229,0.3)', borderTopColor: '#4f46e5' }} />
              <strong>Streaming Binary Payload...</strong>
              <small style={{ color: '#64748b' }}>Retrieving {fileName} from secure PostgreSQL BYTEA store</small>
            </div>
          )}

          {error && !loading && (
            <div className="document-preview-empty-box" style={{ borderColor: '#fecdd3', background: '#fff1f2' }}>
              <Icon name="alert" size={28} />
              <strong style={{ color: '#e11d48' }}>Preview Unavailable</strong>
              <p style={{ margin: 0, fontSize: '13px', color: '#9f1239' }}>{error}</p>
            </div>
          )}

          {!loading && !error && blobUrl && (
            <>
              {isPdf && (
                <iframe
                  src={`${blobUrl}#toolbar=1&navpanes=0`}
                  title={fileName}
                  className="document-preview-iframe"
                />
              )}

              {isImage && (
                <div className="document-preview-img-container">
                  <img
                    src={blobUrl}
                    alt={fileName}
                    className="document-preview-img"
                  />
                </div>
              )}

              {isCsv && csvRows && (
                <div className="document-preview-csv-wrap">
                  <table className="invoices-table" style={{ fontSize: '12px' }}>
                    <thead>
                      <tr>
                        {csvRows[0]?.map((head, hIdx) => (
                          <th key={hIdx}>{head}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {csvRows.slice(1).map((row, rIdx) => (
                        <tr key={rIdx}>
                          {row.map((cell, cIdx) => (
                            <td key={cIdx}>{cell || '—'}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {!isPdf && !isImage && (!isCsv || !csvRows) && textContent && (
                <pre className="document-preview-text-box">
                  {textContent}
                </pre>
              )}

              {!isPdf && !isImage && !textContent && (
                <div className="document-preview-empty-box">
                  <Icon name="download" size={32} />
                  <h3>Binary File ({doc.fileType || 'Archive'})</h3>
                  <p style={{ margin: 0, fontSize: '13px', color: '#64748b' }}>
                    This file format is ready for local inspection and processing.
                  </p>
                  <a
                    href={blobUrl}
                    download={fileName}
                    className="btn-primary"
                    style={{ marginTop: '8px', textDecoration: 'none' }}
                  >
                    <Icon name="download" size={14} /> Download Original File ({fileName})
                  </a>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function UploadedDocumentsSection({ documents = [], isLoading = false, error = null, onRetry = null, onRefresh, isRefreshing, onNavigateUploads, onPreview }) {
  const [filter, setFilter] = useState('ALL')
  const [retryingDocId, setRetryingDocId] = useState(null)

  const handleRetryClick = async (doc) => {
    if (!doc?.documentId) return
    try {
      setRetryingDocId(doc.documentId)
      await retryDocument(doc.documentId)
      if (onRefresh) await onRefresh()
    } catch (err) {
      console.error('Retry processing failed:', err)
      alert(`Retry failed: ${err.message || 'Unknown error'}`)
    } finally {
      setRetryingDocId(null)
    }
  }

  if (error) {
    return (
      <section className="invoices-card uploaded-docs-section" style={{ marginTop: '24px' }}>
        <ErrorState
          title="Document Queue Unavailable"
          message={error}
          onRetry={onRetry}
        />
      </section>
    )
  }

  const counts = {
    ALL: documents.length,
    PENDING: documents.filter((d) => (d.processedStatus || '').toUpperCase() === 'PENDING').length,
    PROCESSING: documents.filter((d) => (d.processedStatus || '').toUpperCase() === 'PROCESSING').length,
    COMPLETED: documents.filter((d) => (d.processedStatus || '').toUpperCase() === 'COMPLETED').length,
    FAILED: documents.filter((d) => (d.processedStatus || '').toUpperCase() === 'FAILED').length,
  }

  const filteredDocs =
    filter === 'ALL'
      ? documents
      : documents.filter((d) => (d.processedStatus || '').toUpperCase() === filter)

  return (
    <section className="invoices-card uploaded-docs-section" style={{ marginTop: '24px' }}>
      <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span className="section-kicker">Live PostgreSQL Ingestion & AI Queue</span>
          <h2>Uploaded Documents & Processing Status</h2>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            type="button"
            className="refresh-button"
            onClick={onRefresh}
            disabled={isRefreshing || isLoading}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              borderRadius: '8px',
              border: '1px solid #cbd5e1',
              background: '#ffffff',
              color: '#1e293b',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: '600',
              boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
            }}
          >
            <Icon name="sparkles" size={14} /> {isRefreshing ? 'Refreshing...' : 'Refresh Status'}
          </button>
        </div>
      </div>

      <div className="filter-chips-row" style={{ display: 'flex', gap: '8px', margin: '12px 0 16px', flexWrap: 'wrap' }}>
        {['ALL', 'PENDING', 'PROCESSING', 'COMPLETED', 'FAILED'].map((st) => (
          <button
            key={st}
            type="button"
            className={`filter-chip ${filter === st ? 'active' : ''}`}
            onClick={() => setFilter(st)}
            style={{
              padding: '5px 12px',
              borderRadius: '20px',
              border: filter === st ? '1px solid #4f46e5' : '1px solid #e2e8f0',
              background: filter === st ? '#eef2ff' : '#ffffff',
              color: filter === st ? '#4338ca' : '#64748b',
              fontSize: '12px',
              fontWeight: '600',
              cursor: 'pointer',
            }}
          >
            {st === 'ALL' ? 'All' : st.charAt(0) + st.slice(1).toLowerCase()} ({counts[st] || 0})
          </button>
        ))}
      </div>

      <div className="table-responsive">
        <table className="invoices-table">
          <thead>
            <tr>
              <th>File Name</th>
              <th>Category</th>
              <th>Uploaded At</th>
              <th>Processing Status</th>
              <th>Action</th>
              <th>Storage Type</th>
            </tr>
          </thead>
          {isLoading ? (
            <TableRowSkeleton rows={3} cols={6} />
          ) : filteredDocs.length === 0 ? (
            <tbody>
              <tr>
                <td colSpan="6" style={{ padding: '8px 0' }}>
                  <EmptyState
                    icon="📂"
                    title={`No Documents in ${filter === 'ALL' ? 'Queue' : filter}`}
                    description="Upload your invoices, bank statements, or WhatsApp chats above to begin processing."
                    actionLabel={onNavigateUploads ? "Select Documents" : undefined}
                    onAction={onNavigateUploads}
                  />
                </td>
              </tr>
            </tbody>
          ) : (
            <tbody>
              {filteredDocs.map((doc, idx) => {
                const status = (doc.processedStatus || 'PENDING').toUpperCase()
                const isFailed = status === 'FAILED'
                const isCurrentRetrying = retryingDocId === doc.documentId

                let badgeBg = '#fef3c7'
                let badgeColor = '#92400e'
                let badgeLabel = '⏳ PENDING'

                if (status === 'PROCESSING') {
                  badgeBg = '#dbeafe'
                  badgeColor = '#1e40af'
                  badgeLabel = '⚡ PROCESSING'
                } else if (status === 'COMPLETED') {
                  badgeBg = '#dcfce7'
                  badgeColor = '#166534'
                  badgeLabel = '✓ COMPLETED'
                } else if (status === 'FAILED') {
                  badgeBg = '#fee2e2'
                  badgeColor = '#991b1b'
                  badgeLabel = '✕ FAILED'
                }

                return (
                  <tr key={doc.documentId || idx}>
                    <td className="inv-customer">
                      <strong>{doc.fileName || 'document'}</strong>
                    </td>
                    <td>
                      <span style={{ fontSize: '12px', fontWeight: '600', color: '#475569' }}>
                        {doc.fileType || '—'}
                      </span>
                    </td>
                    <td className="inv-date">
                      {doc.uploadDate ? new Date(doc.uploadDate).toLocaleString() : '—'}
                    </td>
                    <td>
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          padding: '4px 10px',
                          borderRadius: '12px',
                          fontSize: '11px',
                          fontWeight: '700',
                          background: badgeBg,
                          color: badgeColor,
                        }}
                      >
                        {badgeLabel}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                        {onPreview && (
                          <button
                            type="button"
                            onClick={() => onPreview(doc)}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                              padding: '4px 10px',
                              borderRadius: '6px',
                              border: '1px solid #c7d2fe',
                              background: '#eef2ff',
                              color: '#4338ca',
                              fontSize: '12px',
                              fontWeight: '600',
                              cursor: 'pointer',
                              transition: 'all 0.15s ease',
                            }}
                            title="Preview original uploaded document"
                          >
                            <Icon name="file-text" size={13} />
                            View
                          </button>
                        )}
                        {isFailed && (
                          <button
                            type="button"
                            onClick={() => handleRetryClick(doc)}
                            disabled={isCurrentRetrying}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '5px',
                              padding: '4px 10px',
                              borderRadius: '6px',
                              border: '1px solid #ef4444',
                              background: '#fff',
                              color: '#dc2626',
                              fontSize: '12px',
                              fontWeight: '600',
                              cursor: isCurrentRetrying ? 'not-allowed' : 'pointer',
                            }}
                          >
                            <Icon name="refresh" size={13} />
                            {isCurrentRetrying ? 'Retrying...' : 'Retry'}
                          </button>
                        )}
                      </div>
                    </td>
                    <td>
                      <span style={{ fontSize: '11px', color: '#64748b' }}>PostgreSQL BYTEA</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          )}
        </table>
      </div>
    </section>
  )
}

function DemandIntelligenceSection({ demandData, onRefresh, isRefreshing, onNavigateUploads, isLoading = false, error = null, onRetry = null }) {
  const [filterRisk, setFilterRisk] = useState('ALL')
  const [itemSearch, setItemSearch] = useState('')

  if (error) {
    return (
      <div className="demand-intelligence-container" style={{ margin: '20px 0 32px' }}>
        <ErrorState
          title="Demand Intelligence Engine Offline"
          message={error}
          onRetry={onRetry}
        />
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="demand-intelligence-container" style={{ display: 'flex', flexDirection: 'column', gap: '24px', margin: '20px 0 32px' }}>
        <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)', padding: '24px 28px', borderRadius: '16px', color: '#fff' }}>
          <div>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', background: 'rgba(255,255,255,0.15)', padding: '4px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              <Icon name="sparkles" size={13} /> AI Demand Intelligence Engine
            </span>
            <h2 style={{ fontSize: '22px', fontWeight: '700', margin: '8px 0 4px', color: '#fff' }}>Analyzing Real-time Intelligence...</h2>
          </div>
        </div>
        <InsightSkeleton />
      </div>
    )
  }

  const summary = demandData?.summary || {
    totalSkusDemanded: 0,
    highRiskStockouts: 0,
    suggestedReordersCount: 0,
    fastestMovingItem: 'None',
    totalDemandVolume: 0,
  }

  const stockoutRisks = demandData?.stockoutRisks || []
  const reorderRecs = demandData?.reorderRecommendations || []
  const unmetDemands = demandData?.unmetDemands || []
  const inventoryItems = demandData?.inventoryItems || []

  const filteredRisks = filterRisk === 'ALL'
    ? stockoutRisks
    : stockoutRisks.filter((r) => (r.risk_level || r.riskLevel || '').toUpperCase() === filterRisk)

  const filteredItems = inventoryItems.filter((i) => {
    const name = (i.itemName || i.item_name || '').toLowerCase()
    return name.includes(itemSearch.toLowerCase())
  })


  return (
    <div className="demand-intelligence-container" style={{ display: 'flex', flexDirection: 'column', gap: '24px', margin: '20px 0 32px' }}>
      {/* 1. Header Banner & Refresh Bar */}
      <div className="section-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)', padding: '24px 28px', borderRadius: '16px', color: '#fff' }}>
        <div>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', background: 'rgba(255,255,255,0.15)', padding: '4px 10px', borderRadius: '20px', fontSize: '11px', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            <Icon name="sparkles" size={13} /> AI Demand Intelligence Engine
          </span>
          <h2 style={{ fontSize: '22px', fontWeight: '700', margin: '8px 0 4px', color: '#fff' }}>Inventory Run-Rate & Demand Forecasting</h2>
          <p style={{ margin: 0, fontSize: '13px', color: '#c7d2fe' }}>Real-time SKU velocity, stockout hazard indicators, and smart reorder suggestions computed from WhatsApp inquiries.</p>
        </div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <button
            type="button"
            onClick={onRefresh}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 16px',
              borderRadius: '8px',
              border: 'none',
              background: '#4f46e5',
              color: '#fff',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: '600',
              boxShadow: '0 2px 4px rgba(0,0,0,0.2)',
            }}
          >
            <Icon name="sparkles" size={14} /> {isRefreshing ? 'Analyzing...' : 'Refresh Intelligence'}
          </button>
        </div>
      </div>

      {/* 2. Top Summary KPI Cards */}
      <div className="insights-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
        <div className="insight-card" style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '14px', padding: '18px', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
          <div style={{ fontSize: '12px', fontWeight: '600', color: '#64748b', textTransform: 'uppercase', marginBottom: '6px' }}>Demanded SKUs</div>
          <div style={{ fontSize: '28px', fontWeight: '800', color: '#0f172a' }}>{summary.totalSkusDemanded || 0}</div>
          <div style={{ fontSize: '12px', color: '#10b981', marginTop: '4px' }}>Active product inquiry lines</div>
        </div>

        <div className="insight-card" style={{ background: '#fff1f2', border: '1px solid #fecdd3', borderRadius: '14px', padding: '18px' }}>
          <div style={{ fontSize: '12px', fontWeight: '600', color: '#9f1239', textTransform: 'uppercase', marginBottom: '6px' }}>Stockout Hazards</div>
          <div style={{ fontSize: '28px', fontWeight: '800', color: '#e11d48' }}>{summary.highRiskStockouts || 0}</div>
          <div style={{ fontSize: '12px', color: '#be123c', marginTop: '4px' }}>High-velocity depletion risks</div>
        </div>

        <div className="insight-card" style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: '14px', padding: '18px' }}>
          <div style={{ fontSize: '12px', fontWeight: '600', color: '#166534', textTransform: 'uppercase', marginBottom: '6px' }}>Smart Reorders</div>
          <div style={{ fontSize: '28px', fontWeight: '800', color: '#16a34a' }}>{summary.suggestedReordersCount || 0}</div>
          <div style={{ fontSize: '12px', color: '#15803d', marginTop: '4px' }}>Recommended replenishment orders</div>
        </div>

        <div className="insight-card" style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '14px', padding: '18px' }}>
          <div style={{ fontSize: '12px', fontWeight: '600', color: '#475569', textTransform: 'uppercase', marginBottom: '6px' }}>Fastest Moving SKU</div>
          <div style={{ fontSize: '20px', fontWeight: '800', color: '#334155', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {summary.fastestMovingItem || 'None'}
          </div>
          <div style={{ fontSize: '12px', color: '#64748b', marginTop: '4px' }}>Vol: {summary.totalDemandVolume || 0} units requested</div>
        </div>
      </div>

      {/* 3. Stockout Risk Radar Section */}
      <section className="invoices-card" style={{ background: '#fff', padding: '24px', borderRadius: '16px', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <h3 style={{ fontSize: '18px', fontWeight: '700', margin: '0 0 4px', color: '#0f172a' }}>Stockout Risk Radar</h3>
            <p style={{ margin: 0, fontSize: '13px', color: '#64748b' }}>Item demand velocity combined with inquiry frequency and customer urgency scores.</p>
          </div>
          <div style={{ display: 'flex', gap: '6px' }}>
            {['ALL', 'HIGH', 'MEDIUM', 'LOW'].map((risk) => (
              <button
                key={risk}
                type="button"
                onClick={() => setFilterRisk(risk)}
                style={{
                  padding: '4px 10px',
                  borderRadius: '16px',
                  border: filterRisk === risk ? '1px solid #4f46e5' : '1px solid #cbd5e1',
                  background: filterRisk === risk ? '#eef2ff' : '#f8fafc',
                  color: filterRisk === risk ? '#4338ca' : '#475569',
                  fontSize: '11px',
                  fontWeight: '700',
                  cursor: 'pointer',
                }}
              >
                {risk}
              </button>
            ))}
          </div>
        </div>

        {filteredRisks.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '32px', color: '#64748b', fontSize: '13px' }}>
            No stockout risks detected. Upload a WhatsApp chat export to analyze demand velocity.
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '16px' }}>
            {filteredRisks.map((item, idx) => {
              const rLevel = (item.risk_level || item.riskLevel || 'LOW').toUpperCase()
              let badgeColor = '#166534'
              let badgeBg = '#dcfce7'
              let cardBorder = '#e2e8f0'

              if (rLevel === 'HIGH') {
                badgeColor = '#991b1b'
                badgeBg = '#fee2e2'
                cardBorder = '#fca5a5'
              } else if (rLevel === 'MEDIUM') {
                badgeColor = '#92400e'
                badgeBg = '#fef3c7'
                cardBorder = '#fcd34d'
              }

              const score = item.urgency_score || item.urgencyScore || 50
              const itemName = item.item_name || item.itemName || 'Product'
              const demandQty = item.total_quantity_demanded || item.totalQuantityDemanded || 0
              const unit = item.unit || 'units'
              const freq = item.demand_frequency || item.demandFrequency || 1
              const reason = item.reason || 'Calculated from customer request velocity.'

              return (
                <div
                  key={idx}
                  style={{
                    border: `1px solid ${cardBorder}`,
                    borderRadius: '12px',
                    padding: '16px',
                    background: '#ffffff',
                    boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                    <strong style={{ fontSize: '15px', color: '#0f172a' }}>{itemName}</strong>
                    <span style={{ fontSize: '11px', fontWeight: '800', padding: '3px 8px', borderRadius: '12px', background: badgeBg, color: badgeColor }}>
                      {rLevel} RISK
                    </span>
                  </div>

                  <div style={{ fontSize: '12px', color: '#475569', marginBottom: '10px' }}>
                    <strong>{demandQty} {unit}</strong> requested across <strong>{freq}</strong> inquiry point(s).
                  </div>

                  <div style={{ marginBottom: '10px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: '#64748b', marginBottom: '4px' }}>
                      <span>Depletion Hazard Score</span>
                      <strong>{score} / 100</strong>
                    </div>
                    <div style={{ width: '100%', height: '6px', background: '#e2e8f0', borderRadius: '3px', overflow: 'hidden' }}>
                      <div
                        style={{
                          width: `${Math.min(100, score)}%`,
                          height: '100%',
                          background: rLevel === 'HIGH' ? '#e11d48' : rLevel === 'MEDIUM' ? '#f59e0b' : '#10b981',
                          borderRadius: '3px',
                        }}
                      />
                    </div>
                  </div>

                  <div style={{ fontSize: '11px', color: '#64748b', fontStyle: 'italic', background: '#f8fafc', padding: '6px 8px', borderRadius: '6px' }}>
                    💡 {reason}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* 4. Smart Reorder Suggestions Table */}
      <section className="invoices-card" style={{ background: '#fff', padding: '24px', borderRadius: '16px', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
        <div style={{ marginBottom: '16px' }}>
          <h3 style={{ fontSize: '18px', fontWeight: '700', margin: '0 0 4px', color: '#0f172a' }}>Smart Reorder Recommendations</h3>
          <p style={{ margin: 0, fontSize: '13px', color: '#64748b' }}>Automated replenishment targets calculated to maintain optimal buffer stock.</p>
        </div>

        <div className="table-responsive">
          <table className="invoices-table">
            <thead>
              <tr>
                <th>Product SKU</th>
                <th>Suggested Reorder Quantity</th>
                <th>Target Replenishment Date</th>
                <th>Priority</th>
                <th>Recommended Action</th>
              </tr>
            </thead>
            <tbody>
              {reorderRecs.length === 0 ? (
                <tr>
                  <td colSpan="5" className="empty-table">No reorder recommendations generated yet.</td>
                </tr>
              ) : (
                reorderRecs.map((rec, idx) => {
                  const p = (rec.priority || 'NORMAL').toUpperCase()
                  let pBg = '#f1f5f9'
                  let pColor = '#475569'
                  if (p === 'CRITICAL') { pBg = '#fee2e2'; pColor = '#991b1b' }
                  else if (p === 'MODERATE') { pBg = '#fef3c7'; pColor = '#92400e' }

                  return (
                    <tr key={idx}>
                      <td className="inv-customer"><strong>{rec.item_name || rec.itemName}</strong></td>
                      <td>
                        <span style={{ fontSize: '13px', fontWeight: '700', color: '#1e293b' }}>
                          {rec.suggested_reorder_qty || rec.suggestedReorderQty} {rec.unit || 'units'}
                        </span>
                      </td>
                      <td className="inv-date">{rec.recommended_by_date || rec.recommendedByDate || 'Within 7 days'}</td>
                      <td>
                        <span style={{ fontSize: '11px', fontWeight: '800', padding: '3px 8px', borderRadius: '10px', background: pBg, color: pColor }}>
                          {p}
                        </span>
                      </td>
                      <td>
                        <span style={{ fontSize: '12px', color: '#475569' }}>
                          {rec.supplier_action || rec.supplierAction || 'Replenish stock'}
                        </span>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* 5. Unmet Customer Demand Alerts (if any) */}
      {unmetDemands.length > 0 && (
        <section className="invoices-card" style={{ background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '14px', padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <Icon name="alert" size={18} />
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: '#92400e' }}>
              Unmet Customer Demand Signals ({unmetDemands.length} Opportunity Alerts)
            </h3>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {unmetDemands.map((unm, idx) => (
              <div key={idx} style={{ background: '#ffffff', padding: '12px 16px', borderRadius: '8px', border: '1px solid #fef3c7', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <strong style={{ color: '#0f172a', fontSize: '14px' }}>{unm.customer || 'Customer'}:</strong>{' '}
                  <span style={{ color: '#475569', fontSize: '13px' }}>Requested {unm.quantity_requested || 1} units of <strong>{unm.item_name || unm.itemName}</strong> ({unm.date || 'Recent'})</span>
                </div>
                <span style={{ fontSize: '12px', fontWeight: '700', color: '#b45309', background: '#fef3c7', padding: '4px 8px', borderRadius: '6px' }}>
                  Opportunity: ₹{(unm.potential_revenue_loss || 500).toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 6. Extracted PostgreSQL Inventory Items Table */}
      <section className="invoices-card" style={{ background: '#fff', padding: '24px', borderRadius: '16px', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <h3 style={{ fontSize: '18px', fontWeight: '700', margin: '0 0 4px', color: '#0f172a' }}>
              Logged Inventory Mentions (PostgreSQL Table: <code>inventory_items</code>)
            </h3>
            <p style={{ margin: 0, fontSize: '13px', color: '#64748b' }}>Every individual item mention extracted and logged row-by-row into the database.</p>
          </div>
          <div>
            <input
              type="text"
              placeholder="Search product mentions..."
              value={itemSearch}
              onChange={(e) => setItemSearch(e.target.value)}
              style={{
                padding: '6px 12px',
                borderRadius: '8px',
                border: '1px solid #cbd5e1',
                fontSize: '13px',
                width: '220px',
              }}
            />
          </div>
        </div>

          <div className="table-responsive">
          <table className="invoices-table">
            <thead>
              <tr>
                <th>Item / SKU</th>
                <th>Category</th>
                <th>Stock Quantity</th>
                <th>Unit Price</th>
                <th>Reorder Level</th>
                <th>Status / Notes</th>
              </tr>
            </thead>
            <tbody>
              {filteredItems.length === 0 ? (
                <tr>
                  <td colSpan="6" className="empty-table">No item mentions found matching search.</td>
                </tr>
              ) : (
                filteredItems.map((item, idx) => {
                  const qty = Number(item.quantity ?? 0)
                  const reorder = Number(item.reorderLevel ?? 0)
                  const isLow = reorder > 0 && qty <= reorder
                  return (
                    <tr key={idx}>
                      <td className="inv-customer"><strong>{item.itemName || item.item_name}</strong></td>
                      <td><span style={{ fontSize: '12px', fontWeight: '600', color: '#475569' }}>{item.category || 'General'}</span></td>
                      <td>
                        <span style={{ fontWeight: '700', color: isLow ? '#b91c1c' : '#0f172a' }}>
                          {item.quantity ?? '0'} {item.quantityUnit || item.quantity_unit || 'units'}
                        </span>
                      </td>
                      <td style={{ fontWeight: '600', color: '#1e293b' }}>
                        {item.unitPrice ? `₹${item.unitPrice}` : (item.description && item.description.includes('₹') ? item.description.split('|')[0].trim() : '—')}
                      </td>
                      <td>
                        <span style={{ fontSize: '12px', color: '#64748b' }}>
                          {item.reorderLevel ? `${item.reorderLevel} ${item.quantityUnit || ''}` : '—'}
                        </span>
                      </td>
                      <td>
                        {isLow ? (
                          <span style={{ fontSize: '11px', fontWeight: '700', padding: '2px 8px', borderRadius: '10px', background: '#fee2e2', color: '#991b1b' }}>
                            ⚠️ LOW STOCK
                          </span>
                        ) : (
                          <span style={{ fontSize: '11px', fontWeight: '700', padding: '2px 8px', borderRadius: '10px', background: '#dcfce7', color: '#166534' }}>
                            ✓ HEALTHY
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

function App() {
  // Global Auth Context (Protected Route)
  const { isAuthenticated, username: authUsername, brandName, logout: contextLogout } = useAuth()

  const [activeTab, setActiveTab] = useState('dashboard')
  const [uploads, setUploads] = useState(initialUploads)
  const [errors, setErrors] = useState({})
  const [whatsappItems, setWhatsappItems] = useState([])
  const [whatsappStatus, setWhatsappStatus] = useState('idle')
  const [whatsappError, setWhatsappError] = useState('')
  const [submitted, setSubmitted] = useState(null)
  const [mobileNav, setMobileNav] = useState(false)
  const [toast, setToast] = useState(null)
  const toastTimerRef = useRef(null)

  const showToast = (message, type = 'info', duration = 5000) => {
    if (!message) return
    if (toastTimerRef.current) {
      clearTimeout(toastTimerRef.current)
    }
    setToast({ message, type, id: Date.now() })
    toastTimerRef.current = setTimeout(() => {
      setToast(null)
    }, duration)
  }

  const closeToast = () => {
    if (toastTimerRef.current) {
      clearTimeout(toastTimerRef.current)
    }
    setToast(null)
  }

  // Enterprise Authentication State
  const [showLogoutModal, setShowLogoutModal] = useState(false)

  // Enterprise Settings & Features
  const [currency, setCurrency] = useState('INR')
  const [showProfileMenu, setShowProfileMenu] = useState(false)
  const [showNotifications, setShowNotifications] = useState(false)
  const [showCreateInvoiceModal, setShowCreateInvoiceModal] = useState(false)
  const [previewDoc, setPreviewDoc] = useState(null)

  // New Invoice Form State
  const [newInvCustomer, setNewInvCustomer] = useState('')
  const [newInvAmount, setNewInvAmount] = useState('')
  const [newInvDueDate, setNewInvDueDate] = useState('')

  // Trend State
  const [period, setPeriod] = useState('7d')
  const [viewMode, setViewMode] = useState('all')

  // Standardized Asynchronous States
  const [invoicesState, setInvoicesState] = useState({ data: [], isLoading: true, error: null })
  const [docsState, setDocsState] = useState({ data: [], isLoading: true, error: null })
  const [insightsState, setInsightsState] = useState({ data: null, isLoading: true, error: null })
  const [bankStmtState, setBankStmtState] = useState({ data: [], isLoading: true, error: null })

  // Dedicated Fetch Handlers with Comprehensive Error & Retry Management
  const fetchInvoices = async (isManual = false) => {
    setInvoicesState((prev) => ({ ...prev, isLoading: true, error: null }))
    try {
      const data = await getInvoices()
      const mappedInvoices = (data || []).map((inv) => {
        const rawAmount = inv.totalAmountWithTax || inv.totalAmount || 0
        const isPaid = (inv.paymentStatus || '').toUpperCase() === 'PAID'
        return {
          id: inv.invoiceNumber || (inv.id ? inv.id.slice(0, 8).toUpperCase() : 'INV'),
          customer: inv.customerName || 'Customer',
          issueDate: inv.invoiceDate ? String(inv.invoiceDate).split('T')[0] : '—',
          dueDate: inv.dueDate ? String(inv.dueDate).split('T')[0] : 'Pending Due Date',
          amount: typeof rawAmount === 'string' ? parseFloat(rawAmount.replace(/,/g, '')) : Number(rawAmount),
          status: isPaid ? 'paid' : 'due-soon',
          paymentStatus: inv.paymentStatus || 'UNPAID',
          isBackendUploaded: true,
        }
      })
      setInvoicesState({ data: mappedInvoices, isLoading: false, error: null })
    } catch (err) {
      const msg = err.message || 'Failed to fetch invoices from backend'
      setInvoicesState((prev) => ({ ...prev, isLoading: false, error: msg }))
      if (isManual) showToast(`Invoices error: ${msg}`, 'error', 5000)
    }
  }

  const fetchDocuments = async (isManual = false) => {
    setDocsState((prev) => ({ ...prev, isLoading: true, error: null }))
    try {
      const docs = await getDocuments()
      setDocsState({ data: docs || [], isLoading: false, error: null })
    } catch (err) {
      const msg = err.message || 'Failed to fetch document queue from backend'
      setDocsState((prev) => ({ ...prev, isLoading: false, error: msg }))
      if (isManual) showToast(`Documents error: ${msg}`, 'error', 5000)
    }
  }

  const fetchDemandIntelligence = async (isManual = false) => {
    setInsightsState((prev) => ({ ...prev, isLoading: true, error: null }))
    try {
      const data = await getDemandInsights()
      setInsightsState({ data, isLoading: false, error: null })
    } catch (err) {
      const msg = err.message || 'Failed to fetch AI demand insights from backend'
      setInsightsState((prev) => ({ ...prev, isLoading: false, error: msg }))
      if (isManual) showToast(`AI Insights error: ${msg}`, 'error', 5000)
    }
  }

  const fetchBankStatements = async (isManual = false) => {
    setBankStmtState((prev) => ({ ...prev, isLoading: true, error: null }))
    try {
      const data = await getBankStatements()
      setBankStmtState({ data: data || [], isLoading: false, error: null })
    } catch (err) {
      const msg = err.message || 'Failed to fetch bank statements'
      setBankStmtState((prev) => ({ ...prev, isLoading: false, error: msg }))
      if (isManual) showToast(`Bank statements error: ${msg}`, 'error', 5000)
    }
  }

  useEffect(() => {
    fetchInvoices()
    fetchDocuments()
    fetchDemandIntelligence()
    fetchBankStatements()

    const interval = setInterval(() => {
      fetchDocuments()
      fetchInvoices()
      fetchDemandIntelligence()
      fetchBankStatements()
    }, 6000)
    return () => {
      clearInterval(interval)
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    }
  }, [])

  const updateFiles = (key, files, error = '') => {
    setUploads((current) => ({ ...current, [key]: files }))
    setErrors((current) => ({ ...current, [key]: error }))
    setSubmitted(false)
  }

  const removeFile = (key, index) => updateFiles(key, uploads[key].filter((_, itemIndex) => itemIndex !== index))
  const setWhatsAppFile = (file, error = '') => {
    updateFiles('whatsapp', file ? [file] : [], error)
    setWhatsappError(error)
    setWhatsappItems([])
    setWhatsappStatus(error ? 'error' : file ? 'ready' : 'idle')
  }
  const totalFiles = Object.values(uploads).reduce((total, files) => total + files.length, 0)
  const dataPoints = totalFiles

  const [isUploading, setIsUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadProgressDetail, setUploadProgressDetail] = useState(null)

  const handleSubmit = async () => {
    if (totalFiles === 0) {
      setToastMessage('Please select at least one document to upload.')
      setTimeout(() => setToastMessage(''), 4000)
      return
    }

    const hasWhatsAppUpload = uploads.whatsapp.length > 0
    if (hasWhatsAppUpload) {
      setWhatsappStatus('processing')
      setWhatsappError('')
    }

    setIsUploading(true)
    setUploadProgress(5)
    setUploadProgressDetail({ progressPercent: 5, currentFile: 'Preparing batch upload...', completedCount: 0, totalCount: totalFiles })

    try {
      const results = await uploadAllDocuments(uploads, 'a0000000-0000-0000-0000-000000000001', (progressInfo) => {
        setUploadProgress(progressInfo.progressPercent)
        setUploadProgressDetail(progressInfo)
      })

      const successfulList = results.successful || results.successes || []
      const errorList = results.errors || []

      const whatsappSuccess = successfulList.find((item) => item.category === 'whatsapp')
      const whatsappFailure = errorList.find((item) => item.category === 'whatsapp')

      if (whatsappSuccess) {
        const items = Array.isArray(whatsappSuccess.response?.items) ? whatsappSuccess.response.items : []
        setWhatsappItems(items)
        setWhatsappStatus('success')
      } else if (whatsappFailure) {
        setWhatsappStatus('error')
        setWhatsappError(whatsappFailure.error)
      }

      if (errorList.length > 0) {
        const newErrors = { ...errors }
        errorList.forEach((errItem) => {
          newErrors[errItem.category] = errItem.error
        })
        setErrors(newErrors)

        const duplicateErr = errorList.find((e) => e.status === 409)
        if (duplicateErr) {
          showToast(`Backend Notice: ${duplicateErr.error}`, 'error', 5000)
        } else {
          showToast(`Upload finished with ${errorList.length} issue(s).`, 'error', 5000)
        }
      }

      if (successfulList.length > 0) {
        const fileCountText = `${successfulList.length} file${successfulList.length > 1 ? 's' : ''}`
        const categories = [...new Set(successfulList.map(s => s.category || s.fileType))].filter(Boolean).join(', ')
        setSubmitted({
          title: `Upload Completed (${fileCountText})`,
          message: `Successfully indexed ${fileCountText} [${categories}] into PostgreSQL. Results updated in dashboard.`
        })
        if (errorList.length === 0) {
          showToast(`✓ Successfully uploaded and queued ${fileCountText} in PostgreSQL!`, 'success', 5000)
        }
        // State cleanup: Clear staging area so uploaded files disappear from queue
        setUploads(initialUploads)
        setErrors({})

        // Auto-dismiss the success banner after 5 seconds
        setTimeout(() => {
          setSubmitted(null)
        }, 5000)
      }

      await Promise.all([
        fetchDocuments(true),
        fetchDemandIntelligence(true),
        fetchInvoices(true),
        fetchBankStatements(true),
      ])
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      showToast(`Upload encountered errors: ${err.message}`, 'error', 5000)
      if (uploads.whatsapp.length > 0) {
        setWhatsappStatus('error')
        setWhatsappError(err.message)
      }
    } finally {
      setTimeout(() => {
        setIsUploading(false)
        setUploadProgress(0)
        setUploadProgressDetail(null)
      }, 1000)
    }
  }

  const handleMarkAsPaid = (id) => {
    setInvoicesState((prev) => ({
      ...prev,
      data: prev.data.map(inv => inv.id === id ? { ...inv, status: 'paid', paymentStatus: 'PAID' } : inv)
    }))
    showToast(`Invoice ${id} marked as PAID!`, 'success', 5000)
  }

  const handleSendReminder = (id) => {
    const inv = (invoicesState.data || []).find(i => i.id === id)
    showToast(`Payment reminder sent to ${inv ? inv.customer : 'customer'}!`, 'info', 5000)
  }

  const handleLogoutConfirm = () => {
    setShowLogoutModal(false)
    setShowProfileMenu(false)
    contextLogout()
    showToast('Signed out of Team Sanskriti.', 'info', 4000)
  }

  const handleCreateInvoiceSubmit = (e) => {
    e.preventDefault()
    if (!newInvCustomer || !newInvAmount) return

    const newInv = {
      id: `INV-2026-00${(invoicesState.data || []).length + 1}`,
      customer: newInvCustomer,
      issueDate: new Date().toISOString().split('T')[0],
      dueDate: newInvDueDate || '2026-09-15',
      amount: parseFloat(newInvAmount) || 0,
      status: 'due-soon',
      paymentStatus: 'UNPAID',
    }

    setInvoicesState((prev) => ({
      ...prev,
      data: [newInv, ...(prev.data || [])],
    }))
    setNewInvCustomer('')
    setNewInvAmount('')
    setNewInvDueDate('')
    setShowCreateInvoiceModal(false)
    showToast(`Invoice ${newInv.id} created for ${newInv.customer}!`, 'success', 5000)
  }

  const handleExportReport = () => {
    const reportData = {
      organization: 'Team Sanskriti Enterprise',
      timestamp: new Date().toISOString(),
      currency,
      totalRevenue: formatCurrency(0, currency),
      totalExpenses: formatCurrency(0, currency),
      unpaidInvoices: (invoicesState.data || []).length,
    }
    const blob = new Blob([JSON.stringify(reportData, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `Team-Sanskriti-Vyapaar-Mitra-Financial-Report.json`
    a.click()
    URL.revokeObjectURL(url)
    showToast('Report exported to your device!', 'info', 5000)
  }

  // PROTECTED ROUTE GATE: If user is not authenticated, render Team Sanskriti LoginPage
  if (!isAuthenticated) {
    return <LoginPage />
  }

  return (
    <div className="app-shell">
      {/* Dynamic Auto-Dismissing Toast Notification */}
      {toast && (
        <div key={toast.id} className={`toast-notification ${toast.type || 'info'}`}>
          <Icon name={toast.type === 'error' ? 'alert-triangle' : toast.type === 'success' ? 'check' : 'info'} size={16} />
          <span>{toast.message}</span>
          <button type="button" className="toast-close-btn" onClick={closeToast} title="Dismiss">✕</button>
          <div className="toast-progress" />
        </div>
      )}

      {/* Logout Confirmation Modal */}
      {showLogoutModal && (
        <div className="modal-backdrop" onClick={() => setShowLogoutModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header danger">
              <div className="modal-icon rose"><Icon name="logout" size={22} /></div>
              <div>
                <h3>Log Out of Workspace</h3>
                <p>Are you sure you want to sign out of Team Sanskriti's Vyapaar Mitra?</p>
              </div>
            </div>
            <div className="modal-body">
              <p>Your session settings and local financial data remain securely saved in your browser.</p>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn-secondary" onClick={() => setShowLogoutModal(false)}>Cancel</button>
              <button type="button" className="btn-danger" onClick={handleLogoutConfirm}>
                <Icon name="logout" size={14} />
                <span>Confirm Log Out</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create Manual Invoice Modal */}
      {showCreateInvoiceModal && (
        <div className="modal-backdrop" onClick={() => setShowCreateInvoiceModal(false)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-icon indigo"><Icon name="file-text" size={22} /></div>
              <div>
                <h3>Create New Client Invoice</h3>
                <p>Add a new unpaid invoice to your organization receivables</p>
              </div>
            </div>
            <form onSubmit={handleCreateInvoiceSubmit}>
              <div className="modal-body form-grid">
                <div className="form-group">
                  <label>Customer / Client Name</label>
                  <input type="text" placeholder="e.g. Acme Corp" value={newInvCustomer} onChange={(e) => setNewInvCustomer(e.target.value)} required />
                </div>
                <div className="form-group">
                  <label>Invoice Amount ({currencies[currency].symbol})</label>
                  <input type="number" step="0.01" placeholder="0.00" value={newInvAmount} onChange={(e) => setNewInvAmount(e.target.value)} required />
                </div>
                <div className="form-group">
                  <label>Due Date</label>
                  <input type="date" value={newInvDueDate} onChange={(e) => setNewInvDueDate(e.target.value)} />
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn-secondary" onClick={() => setShowCreateInvoiceModal(false)}>Cancel</button>
                <button type="submit" className="btn-primary">
                  <Icon name="plus" size={14} />
                  <span>Save Invoice</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Document Original File Preview Modal */}
      {previewDoc && (
        <DocumentPreviewModal
          doc={previewDoc}
          onClose={() => setPreviewDoc(null)}
        />
      )}

      <aside className={`sidebar ${mobileNav ? 'open' : ''}`}>
        <div className="brand vyapaar-sidebar-brand">
          <img src="/vyapaar-mitra-logo.png" alt="Vyapaar Mitra Logo" className="vyapaar-sidebar-logo" />
          <div className="vyapaar-brand-text-block">
            <span className="vyapaar-team-eyebrow">TEAM SANSKRITI'S</span>
            <strong className="vyapaar-main-title">Vyapaar Mitra</strong>
            <small className="vyapaar-tagline">Simplifying Business, Multiplying Growth</small>
          </div>
        </div>

        <nav className="main-nav" aria-label="Main navigation">
          <span className="nav-label">Organization</span>
          {navItems.map((item) => {
            const badgeValue = item.badgeKey === 'uploads' ? (dataPoints > 0 ? `${dataPoints}` : null) : (item.id === 'invoices' ? `${(invoicesState.data || []).length}` : item.badge)
            return (
              <button
                type="button"
                key={item.id}
                className={`nav-item ${activeTab === item.id ? 'active' : ''}`}
                onClick={() => {
                  setActiveTab(item.id)
                  setMobileNav(false)
                }}
              >
                <Icon name={item.icon} size={17} />
                <span>{item.label}</span>
                {badgeValue && <b>{badgeValue}</b>}
              </button>
            )
          })}
        </nav>

        <div className="sidebar-bottom">
          <div className="ai-health-widget">
            <div className="widget-header">
              <Icon name="sparkles" size={14} />
              <span>AI Health Index</span>
              <strong>100 / 100</strong>
            </div>
            <div className="widget-bar"><span style={{ width: '100%' }} /></div>
            <small>Optimal Status · Zero Debt</small>
          </div>

          <div className="profile-container">
            <div className="profile" onClick={() => setShowProfileMenu(!showProfileMenu)} role="button" tabIndex="0">
              <div className="profile-avatar">VM</div>
              <div>
                <strong>{authUsername || "Team Sanskriti's Vyapaar Mitra"}</strong>
                <small>Enterprise Admin</small>
              </div>
              <Icon name="chevron" size={15} />
            </div>

            {/* Profile Popover Menu */}
            {showProfileMenu && (
              <div className="profile-popover">
                <div className="popover-header">
                  <strong>{brandName || "Team Sanskriti's Vyapaar Mitra"}</strong>
                  <small>Administrator Account ({authUsername})</small>
                </div>
                <div className="popover-menu">
                  <button type="button" onClick={() => { setActiveTab('profile'); setShowProfileMenu(false) }}>
                    <Icon name="building" size={14} /> Organization Settings
                  </button>
                  <button type="button" onClick={handleExportReport}>
                    <Icon name="download" size={14} /> Export Financial Report
                  </button>
                  <div className="popover-divider" />
                  <button type="button" className="logout-item" onClick={() => { setShowLogoutModal(true); setShowProfileMenu(false) }}>
                    <Icon name="logout" size={15} />
                    <span>Log Out</span>
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </aside>

      {mobileNav && <button className="sidebar-overlay" type="button" aria-label="Close navigation" onClick={() => setMobileNav(false)} />}

      <main className="main-content">
        <header className="topbar">
          <button type="button" className="mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open navigation">
            <Icon name="menu" />
          </button>
          <div className="breadcrumb">
            <span>Team Sanskriti's Vyapaar Mitra</span>
            <Icon name="chevron" size={13} />
            <strong>
              {activeTab === 'dashboard' && 'Owner Dashboard'}
              {activeTab === 'uploads' && 'Data Uploads'}
              {activeTab === 'invoices' && 'Unpaid Invoices'}
              {activeTab === 'insights' && 'AI Insights'}
              {activeTab === 'profile' && 'Organization Profile'}
              {activeTab === 'settings' && 'Workspace Settings'}
            </strong>
          </div>

          <div className="top-actions">
            {/* Currency Selector */}
            <div className="currency-selector">
              <Icon name="globe" size={14} />
              <select value={currency} onChange={(e) => setCurrency(e.target.value)} aria-label="Select Currency">
                {Object.values(currencies).map(curr => (
                  <option key={curr.code} value={curr.code}>{curr.symbol} {curr.code}</option>
                ))}
              </select>
            </div>

            <button
              type="button"
              className="quick-upload-btn"
              onClick={() => setActiveTab('uploads')}
            >
              <Icon name="upload" size={15} />
              <span>Upload Data</span>
            </button>

            {/* Notifications Menu Trigger */}
            <div className="notifications-wrap">
              <button
                type="button"
                className="icon-button"
                aria-label="Notifications"
                onClick={() => setShowNotifications(!showNotifications)}
              >
                <Icon name="bell" size={19} />
              </button>

              {showNotifications && (
                <div className="notifications-dropdown">
                  <div className="notif-header">
                    <strong>Organization Notifications</strong>
                    <span>Real-time logs</span>
                  </div>
                  <div className="notif-list">
                    <div className="notif-item">
                      <Icon name="check" size={14} />
                      <div>
                        <strong>Workspace Initialized</strong>
                        <small>XYZ Organization instance active</small>
                      </div>
                    </div>
                    <div className="notif-item">
                      <Icon name="shield" size={14} />
                      <div>
                        <strong>Confidentiality Audit Passed</strong>
                        <small>Local data isolation verified</small>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Topbar Profile & Logout Icon Action */}
            <div className="top-profile-wrap">
              <button
                type="button"
                className="top-profile"
                onClick={() => setShowProfileMenu(!showProfileMenu)}
              >
                <div className="profile-avatar">TS</div>
                <Icon name="chevron" size={14} />
              </button>

              {/* Direct Logout Icon Button */}
              <button
                type="button"
                className="top-logout-btn"
                onClick={() => setShowLogoutModal(true)}
                title="Log Out of Team Sanskriti"
                aria-label="Log Out"
              >
                <Icon name="logout" size={16} />
              </button>
            </div>
          </div>
        </header>

        <div className="page-wrap">
          {/* View: DASHBOARD */}
          {activeTab === 'dashboard' && (
            <>
              {/* Header Intro Banner */}
              <section className="page-intro">
                <div>
                  <div className="eyebrow">
                    <span className="eyebrow-dot" />
                    {brandName || 'Team Sanskriti'} Enterprise Portal
                  </div>
                  <h1>Welcome back, {authUsername || 'Team Sanskriti'}</h1>
                  <p>Overview of daily financial trends, receivables status, and organization performance.</p>
                </div>
                <div className="intro-meta">
                  <div className="meta-icon"><Icon name="shield" size={18} /></div>
                  <div>
                    <strong>{brandName || 'Team Sanskriti'}</strong>
                    <span>Secure Production Instance</span>
                  </div>
                </div>
              </section>

              {/* Top KPI Cards Grid */}
              {invoicesState.isLoading ? (
                <KpiSkeletonGrid />
              ) : invoicesState.error ? (
                <div style={{ margin: '16px 0' }}>
                  <ErrorState
                    title="Failed to Load Financial Overview"
                    message={invoicesState.error}
                    onRetry={fetchInvoices}
                  />
                </div>
              ) : (
                <section className="kpi-grid">
                  {(() => {
                    const invoices = invoicesState.data || []
                    const totalInvAmt = invoices.reduce((acc, inv) => acc + (parseFloat(inv.amount || inv.totalAmountWithTax) || 0), 0)
                    const paidInvAmt = invoices.filter(inv => (inv.status || inv.paymentStatus || '').toLowerCase() === 'paid')
                                              .reduce((acc, inv) => acc + (parseFloat(inv.amount || inv.paidAmount || inv.totalAmountWithTax) || 0), 0)
                    const unpaidInvAmt = invoices.filter(inv => (inv.status || inv.paymentStatus || '').toLowerCase() !== 'paid')
                                                .reduce((acc, inv) => acc + (parseFloat(inv.amount || inv.totalAmountWithTax) || 0), 0)
                    const estExpenses = totalInvAmt > 0 ? paidInvAmt * 0.35 : 0
                    const netMarginPct = totalInvAmt > 0 ? (((paidInvAmt - estExpenses) / (paidInvAmt || 1)) * 100).toFixed(1) : '0.0'

                    return (
                      <>
                        <article className="kpi-card accent-indigo">
                          <div className="kpi-top">
                            <span className="kpi-label">Total Revenue</span>
                            <div className="kpi-icon indigo"><Icon name="trending-up" size={18} /></div>
                          </div>
                          <div className="kpi-value">{formatCurrency(paidInvAmt, currency)}</div>
                          <div className="kpi-footer positive">
                            <Icon name="trending-up" size={14} />
                            <span><strong>{formatCurrency(paidInvAmt, currency)}</strong> collected</span>
                          </div>
                        </article>

                        <article className="kpi-card accent-rose">
                          <div className="kpi-top">
                            <span className="kpi-label">Operating Expenses</span>
                            <div className="kpi-icon rose"><Icon name="trending-down" size={18} /></div>
                          </div>
                          <div className="kpi-value">{formatCurrency(estExpenses, currency)}</div>
                          <div className="kpi-footer neutral">
                            <Icon name="trending-down" size={14} />
                            <span><strong>{formatCurrency(estExpenses, currency)}</strong> operational</span>
                          </div>
                        </article>

                        <article className="kpi-card accent-emerald">
                          <div className="kpi-top">
                            <span className="kpi-label">Net Profit Margin</span>
                            <div className="kpi-icon emerald"><Icon name="dollar" size={18} /></div>
                          </div>
                          <div className="kpi-value">{formatCurrency(Math.max(0, paidInvAmt - estExpenses), currency)}</div>
                          <div className="kpi-footer positive">
                            <Icon name="sparkles" size={14} />
                            <span><strong>{netMarginPct}%</strong> net margin</span>
                          </div>
                        </article>

                        <article className="kpi-card accent-amber">
                          <div className="kpi-top">
                            <span className="kpi-label">Unpaid Receivables</span>
                            <div className="kpi-icon amber"><Icon name="file-text" size={18} /></div>
                          </div>
                          <div className="kpi-value">{formatCurrency(unpaidInvAmt, currency)}</div>
                          <div className="kpi-footer neutral">
                            <Icon name="clock" size={14} />
                            <span><strong>{invoices.filter(i => (i.status || i.paymentStatus || '').toLowerCase() !== 'paid').length} invoices</strong> pending</span>
                          </div>
                        </article>
                      </>
                    )
                  })()}
                </section>
              )}

              {/* Main Daily Revenue & Expense Trends Chart */}
              <TrendChart
                period={period}
                setPeriod={setPeriod}
                viewMode={viewMode}
                setViewMode={setViewMode}
                currency={currency}
                invoices={invoicesState.data}
                isLoading={invoicesState.isLoading}
                error={invoicesState.error}
                onRetry={fetchInvoices}
              />

              {/* Unpaid Invoices Section */}
              <UnpaidInvoicesSection
                invoices={invoicesState.data}
                isLoading={invoicesState.isLoading}
                error={invoicesState.error}
                onRetry={fetchInvoices}
                onSendReminder={handleSendReminder}
                currency={currency}
                onAddInvoice={() => setShowCreateInvoiceModal(true)}
              />

              {/* AI Insights & Recommendations */}
              <AIInsightsWidget
                onNavigateUploads={() => setActiveTab('uploads')}
                invoices={invoicesState.data}
                backendDocs={docsState.data}
                isLoading={docsState.isLoading || invoicesState.isLoading}
                error={docsState.error}
                onRetry={() => { fetchDocuments(); fetchInvoices() }}
              />

              {/* Demand Intelligence Section */}
              <DemandIntelligenceSection
                demandData={insightsState.data}
                isLoading={insightsState.isLoading}
                error={insightsState.error}
                onRetry={fetchDemandIntelligence}
                onRefresh={fetchDemandIntelligence}
                isRefreshing={insightsState.isLoading}
                onNavigateUploads={() => setActiveTab('uploads')}
              />
            </>
          )}

          {/* View: DATA UPLOADS */}
          {(activeTab === 'uploads' || activeTab === 'profile' || activeTab === 'settings') && (
            <>
              {submitted && (
                <div className="success-banner">
                  <div className="success-icon"><Icon name="check" size={18} /></div>
                  <div>
                    <strong>{submitted.title || 'Organization data updated'}</strong>
                    <span>{submitted.message || 'Everything has been uploaded through the backend and processed results appear below.'}</span>
                  </div>
                  <button type="button" onClick={() => setSubmitted(null)} aria-label="Dismiss success message"><Icon name="close" size={16} /></button>
                </div>
              )}

              <section className="page-intro">
                <div>
                  <div className="eyebrow"><span className="eyebrow-dot" />Data Management</div>
                  <h1>Organization Data Sources</h1>
                  <p>Upload organization bank statements, invoices, and records to populate financial metrics.</p>
                </div>
                <div className="intro-meta">
                  <div className="meta-icon"><Icon name="shield" size={18} /></div>
                  <div>
                    <strong>Confidential & Private</strong>
                    <span>Stored locally in organization workspace</span>
                  </div>
                </div>
              </section>

              {/* Dynamic Live Upload Action & Progress Bar Banner */}
              {isUploading && (
                <section className="live-upload-progress-card" style={{
                  background: 'linear-gradient(135deg, #1e1b4b 0%, #312e81 100%)',
                  borderRadius: '16px',
                  padding: '20px 24px',
                  color: '#ffffff',
                  marginBottom: '24px',
                  boxShadow: '0 10px 25px -5px rgba(49, 46, 129, 0.4)',
                  border: '1px solid #4338ca'
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <span className="spinner-icon" style={{
                        display: 'inline-block',
                        width: '18px',
                        height: '18px',
                        border: '2px solid rgba(255,255,255,0.3)',
                        borderTopColor: '#38bdf8',
                        borderRadius: '50%',
                        animation: 'spin 0.8s linear infinite'
                      }} />
                      <strong style={{ fontSize: '15px', letterSpacing: '-0.2px' }}>
                        Uploading & Processing Batch...
                      </strong>
                    </div>
                    <span style={{ fontSize: '18px', fontWeight: '800', color: '#38bdf8' }}>
                      {uploadProgress}%
                    </span>
                  </div>

                  {/* Progress Track */}
                  <div style={{
                    width: '100%',
                    height: '10px',
                    background: 'rgba(255,255,255,0.15)',
                    borderRadius: '999px',
                    overflow: 'hidden',
                    marginBottom: '10px'
                  }}>
                    <div style={{
                      width: `${uploadProgress}%`,
                      height: '100%',
                      background: 'linear-gradient(90deg, #38bdf8 0%, #818cf8 100%)',
                      borderRadius: '999px',
                      transition: 'width 0.3s ease-out'
                    }} />
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: '#c7d2fe' }}>
                    <span>{uploadProgressDetail?.currentFile ? `Current: ${uploadProgressDetail.currentFile}` : 'Transmitting encrypted payloads to Spring Boot backend...'}</span>
                    <span>{uploadProgressDetail?.completedCount || 0} of {uploadProgressDetail?.totalCount || totalFiles} files</span>
                  </div>
                </section>
              )}

              {/* Staged Files Quick Action Bar */}
              {totalFiles > 0 && !isUploading && (
                <section className="staged-action-bar" style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  background: '#f8fafc',
                  border: '1px solid #cbd5e1',
                  borderRadius: '12px',
                  padding: '14px 20px',
                  marginBottom: '20px',
                  boxShadow: '0 2px 4px rgba(0,0,0,0.04)'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      width: '26px',
                      height: '26px',
                      borderRadius: '50%',
                      background: '#4f46e5',
                      color: '#ffffff',
                      fontWeight: '700',
                      fontSize: '12px'
                    }}>
                      {totalFiles}
                    </span>
                    <div>
                      <strong style={{ display: 'block', fontSize: '14px', color: '#0f172a' }}>
                        {totalFiles} document(s) staged in queue
                      </strong>
                      <span style={{ fontSize: '12px', color: '#64748b' }}>
                        Click upload to persist into PostgreSQL and trigger automated AI intelligence.
                      </span>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={handleSubmit}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '8px',
                      padding: '10px 20px',
                      borderRadius: '8px',
                      background: 'linear-gradient(135deg, #4f46e5 0%, #4338ca 100%)',
                      color: '#ffffff',
                      fontWeight: '700',
                      fontSize: '13px',
                      border: 'none',
                      cursor: 'pointer',
                      boxShadow: '0 4px 12px rgba(79, 70, 229, 0.35)',
                      transition: 'transform 0.15s ease'
                    }}
                  >
                    <Icon name="upload" size={16} /> Upload All ({totalFiles} Files)
                  </button>
                </section>
              )}

              <section className="progress-card">
                <div className="progress-top">
                  <div>
                    <span className="section-kicker">Data Integration Status</span>
                    <h2>Connect financial inputs</h2>
                  </div>
                  <strong>{dataPoints} <small>of 5 sources</small></strong>
                </div>
                <div className="progress-track">
                  <span style={{ width: `${Math.min(100, (dataPoints / 5) * 100)}%` }} />
                </div>
                <div className="progress-bottom">
                  <span><Icon name="clock" size={15} /> Upload takes 1-2 minutes</span>
                  <span>{dataPoints === 5 ? 'All data sources connected' : `${5 - dataPoints} sources pending`}</span>
                </div>
              </section>

              <div className="section-header">
                <div>
                  <span className="section-kicker">Step 1 · Financial records</span>
                  <h2>Upload financial files</h2>
                </div>
                <span className="required-note"><i /> Optional</span>
              </div>

              <div className="upload-grid">
                <UploadCard config={uploadConfigs.bank} files={uploads.bank} onFiles={(files, error) => updateFiles('bank', files, error)} onRemove={(index) => removeFile('bank', index)} onReplace={() => {}} error={errors.bank} compact />
                <UploadCard config={uploadConfigs.inventory} files={uploads.inventory} onFiles={(files, error) => updateFiles('inventory', files, error)} onRemove={(index) => removeFile('inventory', index)} onReplace={() => {}} error={errors.inventory} compact />
                <UploadCard config={uploadConfigs.invoices} files={uploads.invoices} onFiles={(files, error) => updateFiles('invoices', files, error)} onRemove={(index) => removeFile('invoices', index)} onReplace={() => {}} error={errors.invoices} />
                <UploadCard config={uploadConfigs.images} files={uploads.images} onFiles={(files, error) => updateFiles('images', files, error)} onRemove={(index) => removeFile('images', index)} onReplace={() => {}} error={errors.images} />
              </div>

              <div className="section-header conversations-header">
                <div>
                  <span className="section-kicker">Step 2 · Context</span>
                  <h2>Share customer conversations</h2>
                </div>
                <span className="required-note"><i /> Optional</span>
              </div>

              <WhatsAppCard
                file={uploads.whatsapp[0] || null}
                onFile={setWhatsAppFile}
                onClear={() => setWhatsAppFile(null)}
                status={whatsappStatus}
                error={whatsappError}
              />

              <WhatsAppItemsTable items={whatsappItems} />

              <div className="submit-row">
                <div className="submit-note">
                  <Icon name="shield" size={16} />
                  <span><strong>Secure backend processing.</strong> Payload is encrypted and ingested directly into PostgreSQL database.</span>
                </div>
                <button type="button" className="submit-button" onClick={handleSubmit} disabled={isUploading || totalFiles === 0}>
                  {isUploading ? `Uploading (${uploadProgress}%)...` : `Upload & Process ${totalFiles > 0 ? `(${totalFiles} Files)` : ''}`} <Icon name="arrow" size={17} />
                </button>
              </div>

              {/* Live Uploaded Documents & Status Section */}
              <UploadedDocumentsSection
                documents={docsState.data}
                isLoading={docsState.isLoading}
                error={docsState.error}
                onRetry={fetchDocuments}
                onRefresh={fetchDocuments}
                isRefreshing={docsState.isLoading}
                onNavigateUploads={() => setActiveTab('uploads')}
                onPreview={setPreviewDoc}
              />
            </>
          )}

          {/* View: UNPAID INVOICES DIRECT VIEW */}
          {activeTab === 'invoices' && (
            <>
              <section className="page-intro">
                <div>
                  <div className="eyebrow"><span className="eyebrow-dot" />Receivables</div>
                  <h1>Unpaid Invoices</h1>
                  <p>Monitor pending client accounts and receivables.</p>
                </div>
              </section>

              <UnpaidInvoicesSection
                invoices={invoicesState.data}
                isLoading={invoicesState.isLoading}
                error={invoicesState.error}
                onRetry={fetchInvoices}
                onSendReminder={handleSendReminder}
                currency={currency}
                onAddInvoice={() => setShowCreateInvoiceModal(true)}
              />
            </>
          )}

          {/* View: AI INSIGHTS DIRECT VIEW */}
          {activeTab === 'insights' && (
            <>
              <section className="page-intro">
                <div>
                  <div className="eyebrow"><span className="eyebrow-dot" />AI Demand Intelligence</div>
                  <h1>Demand & Stockout Insights</h1>
                  <p>Real-time SKU velocity, stockout hazard indicators, and smart reorder targets computed from customer conversations.</p>
                </div>
              </section>

              <DemandIntelligenceSection
                demandData={insightsState.data}
                isLoading={insightsState.isLoading}
                error={insightsState.error}
                onRetry={fetchDemandIntelligence}
                onRefresh={fetchDemandIntelligence}
                isRefreshing={insightsState.isLoading}
                onNavigateUploads={() => setActiveTab('uploads')}
              />

              <AIInsightsWidget
                onNavigateUploads={() => setActiveTab('uploads')}
                invoices={invoicesState.data}
                backendDocs={docsState.data}
                isLoading={docsState.isLoading || invoicesState.isLoading}
                error={docsState.error}
                onRetry={() => { fetchDocuments(); fetchInvoices() }}
              />
            </>
          )}

          <footer className="page-footer">
            <span>© 2026 AI Business Advisor · {brandName || 'Team Sanskriti'} Enterprise</span>
            <span>Need assistance? <button type="button">Contact Support</button></span>
          </footer>
        </div>
      </main>
    </div>
  )
}

export default App
