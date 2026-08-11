/** Presentation helpers. Nothing here interprets data — it only renders it. */

const DATE_TIME = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'medium',
})

export function formatDateTime(iso: string): string {
  return DATE_TIME.format(new Date(iso))
}

export function formatTokens(tokens: number | null | undefined): string {
  return tokens === null || tokens === undefined ? '—' : tokens.toLocaleString()
}

/**
 * Money, exactly as the API sent it.
 *
 * The value arrives as a decimal string and is prefixed, never parsed: `Number()` on an
 * audit figure is precisely the rounding the backend went out of its way to avoid.
 */
export function formatCost(cost: string | null | undefined): string {
  return cost === null || cost === undefined ? '—' : `$${cost}`
}

/** Wall-clock duration of a run, or `—` while it is still open. */
export function formatDuration(startIso: string, endIso: string | null): string {
  if (endIso === null) return '—'
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime()
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

/** Offset of a step from the run's first recorded moment, e.g. `+0.04s`. */
export function formatOffset(startIso: string, atIso: string): string {
  const seconds = (new Date(atIso).getTime() - new Date(startIso).getTime()) / 1000
  return `+${seconds.toFixed(2)}s`
}

/**
 * A rate in [0, 1] as a percentage, or `—` when the denominator was empty.
 *
 * Null stays visibly different from 0%: "no finished runs to judge" and "this never
 * happens" are different facts on a governance dashboard.
 */
export function formatRate(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return '—'
  const percent = rate * 100
  return `${Number.isInteger(percent) ? percent : percent.toFixed(1)}%`
}

/** Seconds as a short duration, or `—` when there is nothing to average yet. */
export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  return `${seconds.toFixed(2)} s`
}

/** An averaged count (e.g. tokens per run), rounded — or `—` with no data. */
export function formatAverage(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : Math.round(value).toLocaleString()
}

/** Turn `auto_approve` into `Auto approve` — for labels, not for logic. */
export function humanize(value: string): string {
  const spaced = value.replace(/[_-]+/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2)
}
