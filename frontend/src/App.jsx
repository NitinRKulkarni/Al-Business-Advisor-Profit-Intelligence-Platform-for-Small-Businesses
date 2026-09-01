import { useEffect, useRef, useState } from 'react'
import { getDocuments, uploadAllDocuments } from './services/api'

const initialUploads = {
  bank: [],
  invoices: [],
  images: [],
  inventory: [],
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
    title: 'Inventory',
    description: 'Share your current stock list to understand what is moving.',
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

// Zeroed Trend Datasets
const trendDatasets = {
  '7d': [
    { date: 'Mon', revenue: 0, expenses: 0 },
    { date: 'Tue', revenue: 0, expenses: 0 },
    { date: 'Wed', revenue: 0, expenses: 0 },
    { date: 'Thu', revenue: 0, expenses: 0 },
    { date: 'Fri', revenue: 0, expenses: 0 },
    { date: 'Sat', revenue: 0, expenses: 0 },
    { date: 'Sun', revenue: 0, expenses: 0 },
  ],
  '14d': [
    { date: 'Day 1', revenue: 0, expenses: 0 },
    { date: 'Day 2', revenue: 0, expenses: 0 },
    { date: 'Day 3', revenue: 0, expenses: 0 },
    { date: 'Day 4', revenue: 0, expenses: 0 },
    { date: 'Day 5', revenue: 0, expenses: 0 },
    { date: 'Day 6', revenue: 0, expenses: 0 },
    { date: 'Day 7', revenue: 0, expenses: 0 },
    { date: 'Day 8', revenue: 0, expenses: 0 },
    { date: 'Day 9', revenue: 0, expenses: 0 },
    { date: 'Day 10', revenue: 0, expenses: 0 },
    { date: 'Day 11', revenue: 0, expenses: 0 },
    { date: 'Day 12', revenue: 0, expenses: 0 },
    { date: 'Day 13', revenue: 0, expenses: 0 },
    { date: 'Day 14', revenue: 0, expenses: 0 },
  ],
  '30d': [
    { date: 'Week 1', revenue: 0, expenses: 0 },
    { date: 'Week 2', revenue: 0, expenses: 0 },
    { date: 'Week 3', revenue: 0, expenses: 0 },
    { date: 'Week 4', revenue: 0, expenses: 0 },
  ],
  '90d': [
    { date: 'Month 1', revenue: 0, expenses: 0 },
    { date: 'Month 2', revenue: 0, expenses: 0 },
    { date: 'Month 3', revenue: 0, expenses: 0 },
  ],
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

function formatCurrency(amount, currencyCode = 'USD') {
  const curr = currencies[currencyCode] || currencies.USD
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: curr.code, maximumFractionDigits: 2 }).format(amount)
}

function formatBytes(bytes) {
  if (!bytes) return '0 KB'
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function getExtension(name) {
  return `.${name.split('.').pop().toLowerCase()}`
}

// Component: Trend Chart (Interactive SVG with Zero Default Values)
function TrendChart({ period, setPeriod, viewMode, setViewMode, currency }) {
  const [hoveredPoint, setHoveredPoint] = useState(null)
  const data = trendDatasets[period] || trendDatasets['7d']

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
function UnpaidInvoicesSection({ invoices, onSendReminder, currency, onAddInvoice }) {
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [remindedMap, setRemindedMap] = useState({})

  const handleReminder = (id) => {
    setRemindedMap(prev => ({ ...prev, [id]: true }))
    onSendReminder(id)
  }

  const filteredInvoices = invoices.filter(inv => {
    const matchesFilter = filter === 'all' ? true : inv.status === filter
    const matchesSearch = inv.customer.toLowerCase().includes(search.toLowerCase()) || inv.id.toLowerCase().includes(search.toLowerCase())
    return matchesFilter && matchesSearch
  })

  const totalOutstanding = invoices.reduce((acc, inv) => acc + inv.amount, 0)
  const overdueTotal = invoices.filter(inv => inv.status === 'overdue').reduce((acc, inv) => acc + inv.amount, 0)
  const dueSoonTotal = invoices.filter(inv => inv.status === 'due-soon').reduce((acc, inv) => acc + inv.amount, 0)

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
            <button className={`tab-btn overdue ${filter === 'overdue' ? 'active' : ''}`} onClick={() => setFilter('overdue')}>Overdue (0)</button>
            <button className={`tab-btn duesoon ${filter === 'due-soon' ? 'active' : ''}`} onClick={() => setFilter('due-soon')}>Due Soon (0)</button>
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
          <tbody>
            {filteredInvoices.length === 0 ? (
              <tr>
                <td colSpan="7" className="empty-table">
                  <Icon name="file-text" size={32} />
                  <p>No unpaid invoices recorded ({formatCurrency(0, currency)} outstanding balance).</p>
                </td>
              </tr>
            ) : (
              filteredInvoices.map((inv) => (
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
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// Component: AI Insights Advisory Widget
function AIInsightsWidget({ onNavigateUploads, invoices = [], backendDocs = [] }) {
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
            <h3>{totalBackendDocs > 0 ? `${totalBackendDocs} Document(s) Ingested` : 'Connect Organization Financial Sources'}</h3>
            <p>{totalBackendDocs > 0 ? `${totalBackendDocs} financial document(s) uploaded to H2 database and synced with backend.` : "Upload your organization's bank statements or invoices to begin automated financial trend analysis and cash flow monitoring."}</p>
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
            <p>{invoiceCount > 0 ? `${invoiceCount} invoice document(s) synced from H2 backend database staged for payment monitoring.` : 'All accounts are currently up to date with zero outstanding receivables or overdue customer invoices.'}</p>
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

  const handleFiles = (incoming) => {
    const selected = Array.from(incoming)
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
        <input ref={inputRef} className="visually-hidden" type="file" accept={config.accept} multiple={config.multiple} onChange={(event) => handleFiles(event.target.files)} />
        {error && <p className="validation-error"><Icon name="help" size={14} />{error}</p>}
      </div>
    </article>
  )
}

function WhatsAppCard({ value, onChange, onClear }) {
  const maxLength = 5000
  return (
    <article className="upload-card whatsapp-card accent-teal">
      <div className="card-heading">
        <div className="heading-icon"><Icon name="whatsapp" size={22} /></div>
        <div><h3>WhatsApp chats</h3><p>Paste customer conversations to spot recurring questions.</p></div>
        <span className={`card-status ${value.trim() ? 'has-files' : ''}`}><span />{value.trim() ? 'Added' : 'Not added'}</span>
      </div>
      <div className="chat-input-wrap">
        <textarea value={value} onChange={(event) => onChange(event.target.value.slice(0, maxLength))} placeholder="Paste your WhatsApp conversation here..." maxLength={maxLength} aria-label="WhatsApp chat content" />
        <div className="textarea-footer"><span><Icon name="message" size={14} /> Plain text is supported</span><span className={value.length >= maxLength ? 'limit-reached' : ''}>{value.length.toLocaleString()} / {maxLength.toLocaleString()}</span></div>
      </div>
      <button type="button" className="clear-button" onClick={onClear} disabled={!value}><Icon name="trash" size={14} /> Clear chat</button>
    </article>
  )
}

function App() {
  const [activeTab, setActiveTab] = useState('dashboard')
  const [uploads, setUploads] = useState(initialUploads)
  const [errors, setErrors] = useState({})
  const [chats, setChats] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)
  const [toastMessage, setToastMessage] = useState('')

  // Enterprise Authentication State
  const [isLoggedOut, setIsLoggedOut] = useState(false)
  const [showLogoutModal, setShowLogoutModal] = useState(false)

  // Enterprise Settings & Features
  const [currency, setCurrency] = useState('USD')
  const [showProfileMenu, setShowProfileMenu] = useState(false)
  const [showNotifications, setShowNotifications] = useState(false)
  const [showCreateInvoiceModal, setShowCreateInvoiceModal] = useState(false)

  // New Invoice Form State
  const [newInvCustomer, setNewInvCustomer] = useState('')
  const [newInvAmount, setNewInvAmount] = useState('')
  const [newInvDueDate, setNewInvDueDate] = useState('')

  // Trend State
  const [period, setPeriod] = useState('7d')
  const [viewMode, setViewMode] = useState('all')

  // Invoices & Backend Documents State
  const [invoices, setInvoices] = useState(initialInvoices)
  const [backendDocs, setBackendDocs] = useState([])

  const fetchBackendDocuments = async () => {
    try {
      const docs = await getDocuments()
      setBackendDocs(docs || [])
      if (docs && Array.isArray(docs)) {
        const invoiceDocs = docs.filter((d) => d.fileType === 'Invoice')
        const mappedInvoices = invoiceDocs.map((doc, idx) => ({
          id: doc.documentId ? doc.documentId.slice(0, 8).toUpperCase() : `INV-DOC-00${idx + 1}`,
          customer: doc.fileName,
          issueDate: doc.uploadDate ? doc.uploadDate.split('T')[0] : new Date().toISOString().split('T')[0],
          dueDate: 'Pending Ingestion',
          amount: 350.0 + idx * 75.0,
          status: 'due-soon',
          processedStatus: doc.processedStatus,
          isBackendUploaded: true,
        }))
        setInvoices((prev) => {
          const manualInvoices = prev.filter((inv) => !inv.isBackendUploaded)
          return [...mappedInvoices, ...manualInvoices]
        })
      }
    } catch (err) {
      console.warn('Backend documents sync status:', err.message)
    }
  }

  useEffect(() => {
    fetchBackendDocuments()
  }, [])

  const updateFiles = (key, files, error = '') => {
    setUploads((current) => ({ ...current, [key]: files }))
    setErrors((current) => ({ ...current, [key]: error }))
    setSubmitted(false)
  }

  const removeFile = (key, index) => updateFiles(key, uploads[key].filter((_, itemIndex) => itemIndex !== index))
  const totalFiles = Object.values(uploads).reduce((total, files) => total + files.length, 0)
  const dataPoints = totalFiles + (chats.trim() ? 1 : 0)

  const [isUploading, setIsUploading] = useState(false)

  const handleSubmit = async () => {
    if (totalFiles === 0) {
      if (chats.trim()) {
        setSubmitted(true)
        setToastMessage('WhatsApp context saved locally.')
        setTimeout(() => setToastMessage(''), 4000)
        window.scrollTo({ top: 0, behavior: 'smooth' })
      } else {
        setToastMessage('Please select at least one document to upload.')
        setTimeout(() => setToastMessage(''), 4000)
      }
      return
    }

    setIsUploading(true)
    try {
      const results = await uploadAllDocuments(uploads)
      const newErrors = { ...errors }

      if (results.errors.length > 0) {
        results.errors.forEach((errItem) => {
          newErrors[errItem.category] = errItem.error
        })
        setErrors(newErrors)

        const duplicateErr = results.errors.find((e) => e.status === 409)
        if (duplicateErr) {
          setToastMessage(`Backend Notice: ${duplicateErr.error}`)
        } else {
          setToastMessage(`Upload finished with ${results.errors.length} issue(s).`)
        }
      }

      if (results.successes.length > 0) {
        setSubmitted(true)
        if (results.errors.length === 0) {
          setToastMessage(`Successfully uploaded ${results.successes.length} file(s) to backend!`)
        }
      }
      await fetchBackendDocuments()
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      setToastMessage(`Backend upload failed: ${err.message}`)
    } finally {
      setIsUploading(false)
      setTimeout(() => setToastMessage(''), 5000)
    }
  }

  const handleSendReminder = (id) => {
    const inv = invoices.find(i => i.id === id)
    setToastMessage(`Payment reminder sent to ${inv ? inv.customer : 'customer'}!`)
    setTimeout(() => setToastMessage(''), 4000)
  }

  const handleLogoutConfirm = () => {
    setShowLogoutModal(false)
    setShowProfileMenu(false)
    setIsLoggedOut(true)
    setToastMessage('Logged out successfully.')
    setTimeout(() => setToastMessage(''), 4000)
  }

  const handleLoginBack = () => {
    setIsLoggedOut(false)
    setToastMessage('Welcome back, XYZ!')
    setTimeout(() => setToastMessage(''), 4000)
  }

  const handleCreateInvoiceSubmit = (e) => {
    e.preventDefault()
    if (!newInvCustomer || !newInvAmount) return

    const newInv = {
      id: `INV-2026-00${invoices.length + 1}`,
      customer: newInvCustomer,
      issueDate: new Date().toISOString().split('T')[0],
      dueDate: newInvDueDate || '2026-09-15',
      amount: parseFloat(newInvAmount) || 0,
      status: 'sent',
    }

    setInvoices([newInv, ...invoices])
    setNewInvCustomer('')
    setNewInvAmount('')
    setNewInvDueDate('')
    setShowCreateInvoiceModal(false)
    setToastMessage(`Invoice ${newInv.id} created for ${newInv.customer}!`)
    setTimeout(() => setToastMessage(''), 4000)
  }

  const handleExportReport = () => {
    const reportData = {
      organization: 'XYZ Organization',
      timestamp: new Date().toISOString(),
      currency,
      totalRevenue: formatCurrency(0, currency),
      totalExpenses: formatCurrency(0, currency),
      unpaidInvoices: invoices.length,
    }
    const blob = new Blob([JSON.stringify(reportData, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `XYZ-Organization-Financial-Report.json`
    a.click()
    URL.revokeObjectURL(url)
    setToastMessage('Report exported to your device!')
    setTimeout(() => setToastMessage(''), 4000)
  }

  // If user is logged out, render standard organization Login Screen
  if (isLoggedOut) {
    return (
      <div className="login-shell">
        <div className="login-card">
          <div className="login-brand">
            <div className="brand-mark">
              <Icon name="building" size={20} />
            </div>
            <h2>AI Business Advisor</h2>
          </div>
          <span className="login-subtitle">Standard Organization Portal</span>

          <div className="login-user-box">
            <div className="profile-avatar large">XYZ</div>
            <div className="login-user-info">
              <strong>XYZ Organization Admin</strong>
              <small>xyz.admin@organization.internal</small>
            </div>
            <span className="session-pill">Session Timed Out</span>
          </div>

          <div className="login-features-list">
            <div><Icon name="check" size={14} /> Private & confidential local workspace</div>
            <div><Icon name="check" size={14} /> Real-time daily financial trend analysis</div>
            <div><Icon name="check" size={14} /> Receivables & unpaid invoice audit</div>
          </div>

          <button type="button" className="login-button" onClick={handleLoginBack}>
            <Icon name="lock" size={16} />
            <span>Sign Back In as XYZ</span>
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="app-shell">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="toast-notification">
          <Icon name="check" size={16} />
          <span>{toastMessage}</span>
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
                <p>Are you sure you want to sign out of XYZ Organization?</p>
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

      <aside className={`sidebar ${mobileNav ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-mark">
            <Icon name="building" size={16} />
          </div>
          <span>AI Business Advisor</span>
        </div>

        <nav className="main-nav" aria-label="Main navigation">
          <span className="nav-label">Organization</span>
          {navItems.map((item) => {
            const badgeValue = item.badgeKey === 'uploads' ? (dataPoints > 0 ? `${dataPoints}` : null) : (item.id === 'invoices' ? `${invoices.length}` : item.badge)
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
              <div className="profile-avatar">XYZ</div>
              <div>
                <strong>XYZ</strong>
                <small>Business Owner & Admin</small>
              </div>
              <Icon name="chevron" size={15} />
            </div>

            {/* Profile Popover Menu */}
            {showProfileMenu && (
              <div className="profile-popover">
                <div className="popover-header">
                  <strong>XYZ Organization</strong>
                  <small>Administrator Account</small>
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
            <span>Organization Workspace</span>
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
                <div className="profile-avatar">XYZ</div>
                <Icon name="chevron" size={14} />
              </button>

              {/* Direct Logout Icon Button */}
              <button
                type="button"
                className="top-logout-btn"
                onClick={() => setShowLogoutModal(true)}
                title="Log Out of XYZ Organization"
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
                    Standard Organization Portal
                  </div>
                  <h1>Welcome back, XYZ</h1>
                  <p>Overview of daily financial trends, receivables status, and organization performance.</p>
                </div>
                <div className="intro-meta">
                  <div className="meta-icon"><Icon name="shield" size={18} /></div>
                  <div>
                    <strong>Organization Portal</strong>
                    <span>Secure Local Instance</span>
                  </div>
                </div>
              </section>

              {/* Top KPI Cards Grid */}
              <section className="kpi-grid">
                <article className="kpi-card accent-indigo">
                  <div className="kpi-top">
                    <span className="kpi-label">Total Revenue</span>
                    <div className="kpi-icon indigo"><Icon name="trending-up" size={18} /></div>
                  </div>
                  <div className="kpi-value">{formatCurrency(0, currency)}</div>
                  <div className="kpi-footer neutral">
                    <Icon name="trending-up" size={14} />
                    <span><strong>{formatCurrency(0, currency)}</strong> period total</span>
                  </div>
                </article>

                <article className="kpi-card accent-rose">
                  <div className="kpi-top">
                    <span className="kpi-label">Total Expenses</span>
                    <div className="kpi-icon rose"><Icon name="trending-down" size={18} /></div>
                  </div>
                  <div className="kpi-value">{formatCurrency(0, currency)}</div>
                  <div className="kpi-footer neutral">
                    <Icon name="trending-down" size={14} />
                    <span><strong>{formatCurrency(0, currency)}</strong> period total</span>
                  </div>
                </article>

                <article className="kpi-card accent-emerald">
                  <div className="kpi-top">
                    <span className="kpi-label">Net Profit Margin</span>
                    <div className="kpi-icon emerald"><Icon name="dollar" size={18} /></div>
                  </div>
                  <div className="kpi-value">{formatCurrency(0, currency)}</div>
                  <div className="kpi-footer positive">
                    <Icon name="sparkles" size={14} />
                    <span><strong>0.0%</strong> net margin</span>
                  </div>
                </article>

                <article className="kpi-card accent-amber">
                  <div className="kpi-top">
                    <span className="kpi-label">Unpaid Invoices</span>
                    <div className="kpi-icon amber"><Icon name="file-text" size={18} /></div>
                  </div>
                  <div className="kpi-value">{formatCurrency(invoices.reduce((a, b) => a + b.amount, 0), currency)}</div>
                  <div className="kpi-footer neutral">
                    <Icon name="clock" size={14} />
                    <span><strong>{invoices.length} invoices</strong> pending</span>
                  </div>
                </article>
              </section>

              {/* Main Daily Revenue & Expense Trends Chart */}
              <TrendChart
                period={period}
                setPeriod={setPeriod}
                viewMode={viewMode}
                setViewMode={setViewMode}
                currency={currency}
              />

              {/* Unpaid Invoices Section */}
              <UnpaidInvoicesSection
                invoices={invoices}
                onSendReminder={handleSendReminder}
                currency={currency}
                onAddInvoice={() => setShowCreateInvoiceModal(true)}
              />

              {/* AI Insights & Recommendations */}
              <AIInsightsWidget
                onNavigateUploads={() => setActiveTab('uploads')}
                invoices={invoices}
                backendDocs={backendDocs}
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
                    <strong>Organization data updated</strong>
                    <span>Everything has been saved locally for your organization dashboard.</span>
                  </div>
                  <button type="button" onClick={() => setSubmitted(false)} aria-label="Dismiss success message"><Icon name="close" size={16} /></button>
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

              <WhatsAppCard value={chats} onChange={(value) => { setChats(value); setSubmitted(false) }} onClear={() => setChats('')} />

              <div className="submit-row">
                <div className="submit-note">
                  <Icon name="shield" size={16} />
                  <span><strong>Frontend Only.</strong> All values remain strictly within your local browser context.</span>
                </div>
                <button type="button" className="submit-button" onClick={handleSubmit} disabled={isUploading}>
                  {isUploading ? 'Uploading to Backend...' : 'Update Dashboard Data'} <Icon name="arrow" size={17} />
                </button>
              </div>
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
                invoices={invoices}
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
                  <div className="eyebrow"><span className="eyebrow-dot" />AI Intelligence</div>
                  <h1>Organization Insights</h1>
                  <p>Advisory updates and financial health tracking.</p>
                </div>
              </section>

              <AIInsightsWidget
                onNavigateUploads={() => setActiveTab('uploads')}
              />
            </>
          )}

          <footer className="page-footer">
            <span>© 2026 AI Business Advisor · XYZ Organization</span>
            <span>Need assistance? <button type="button">Contact Support</button></span>
          </footer>
        </div>
      </main>
    </div>
  )
}

export default App
