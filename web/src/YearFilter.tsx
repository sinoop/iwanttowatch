import { useState } from 'react'

function parseYear(raw: string): number | null {
  const trimmed = raw.trim()
  if (!trimmed) return null
  if (!/^\d{4}$/.test(trimmed)) return null
  const num = Number(trimmed)
  return num >= 1880 && num <= 2100 ? num : null
}

/**
 * Shared decade + custom year-range filter control for Discover and My Taste.
 */
export function YearFilter({
  decades,
  decade,
  yearMin,
  yearMax,
  onDecade,
  onYearRange,
  allLabel = 'All decades',
  ariaLabel = 'Decade',
  selectClass,
}: {
  decades: number[]
  decade: number | null
  yearMin: number | null
  yearMax: number | null
  onDecade: (value: number | null) => void
  onYearRange: (min: number | null, max: number | null) => void
  allLabel?: string
  ariaLabel?: string
  selectClass: (active: boolean) => string
}) {
  const hasRange = yearMin !== null || yearMax !== null
  const [customMode, setCustomMode] = useState(hasRange)
  const [prevBounds, setPrevBounds] = useState({ yearMin, yearMax })
  const [fromText, setFromText] = useState(yearMin !== null ? String(yearMin) : '')
  const [toText, setToText] = useState(yearMax !== null ? String(yearMax) : '')

  if (prevBounds.yearMin !== yearMin || prevBounds.yearMax !== yearMax) {
    setPrevBounds({ yearMin, yearMax })
    if (hasRange) setCustomMode(true)
    setFromText(yearMin !== null ? String(yearMin) : '')
    setToText(yearMax !== null ? String(yearMax) : '')
  }

  const pageDecades =
    decade !== null && !decades.includes(decade)
      ? [...decades, decade].sort((a, b) => b - a)
      : decades

  const commitRange = (nextFrom: string, nextTo: string) => {
    const min = parseYear(nextFrom)
    const max = parseYear(nextTo)
    if (min !== yearMin || max !== yearMax) {
      onYearRange(min, max)
    }
  }

  const selectValue = customMode ? 'custom' : decade !== null ? String(decade) : ''
  const isActive = decade !== null || hasRange || customMode

  if (pageDecades.length === 0 && !isActive) return null

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <select
        value={selectValue}
        onChange={(e) => {
          const val = e.target.value
          if (val === 'custom') {
            onDecade(null)
            setCustomMode(true)
          } else if (val === '') {
            setCustomMode(false)
            setFromText('')
            setToText('')
            onDecade(null)
            if (hasRange) onYearRange(null, null)
          } else {
            setCustomMode(false)
            setFromText('')
            setToText('')
            if (hasRange) onYearRange(null, null)
            onDecade(Number(val))
          }
        }}
        aria-label={ariaLabel}
        className={selectClass(isActive)}
      >
        <option value="">{allLabel}</option>
        {pageDecades.map((d) => (
          <option key={d} value={d}>
            {d}s
          </option>
        ))}
        <option value="custom">Between years…</option>
      </select>

      {customMode && (
        <div className="flex items-center gap-1">
          <input
            type="text"
            inputMode="numeric"
            maxLength={4}
            value={fromText}
            onChange={(e) => {
              const v = e.target.value.replace(/\D/g, '').slice(0, 4)
              setFromText(v)
              if (v === '' || v.length === 4) commitRange(v, toText)
            }}
            onBlur={() => commitRange(fromText, toText)}
            placeholder="From"
            aria-label="From year"
            className="w-16 rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-center text-sm text-white placeholder-white/40 outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
          />
          <span className="text-xs text-white/40">–</span>
          <input
            type="text"
            inputMode="numeric"
            maxLength={4}
            value={toText}
            onChange={(e) => {
              const v = e.target.value.replace(/\D/g, '').slice(0, 4)
              setToText(v)
              if (v === '' || v.length === 4) commitRange(fromText, v)
            }}
            onBlur={() => commitRange(fromText, toText)}
            placeholder="To"
            aria-label="To year"
            className="w-16 rounded-lg border border-white/10 bg-black/30 px-2 py-1.5 text-center text-sm text-white placeholder-white/40 outline-none focus:border-accent focus:ring-2 focus:ring-accent/30"
          />
        </div>
      )}
    </div>
  )
}
