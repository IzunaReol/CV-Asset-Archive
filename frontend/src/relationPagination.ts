export function nearbyPages(total: number, current: number, radius = 1): number[] {
  if (!Number.isInteger(total) || total < 1) return [1]
  const page = Math.min(total, Math.max(1, Math.trunc(current)))
  return Array.from({ length: total }, (_, index) => index + 1).filter(
    value => value === 1 || value === total || Math.abs(value - page) <= radius,
  )
}
