/**
 * Keyboard steps for a discrete slider, such as the night timeline.
 *
 * A native range input moves on these keys already, but not identically in
 * every browser, and a test under happy-dom cannot see native stepping at
 * all. So the component handles these keys itself and prevents the default,
 * which also keeps the browser from stepping a second time.
 */
type Step = (index: number, last: number) => number

const STEPS: ReadonlyMap<string, Step> = new Map<string, Step>([
  ['ArrowRight', (i) => i + 1],
  ['ArrowUp', (i) => i + 1],
  ['ArrowLeft', (i) => i - 1],
  ['ArrowDown', (i) => i - 1],
  ['Home', () => 0],
  ['End', (_, last) => last],
])

/**
 * The index after pressing `key` on a slider with `count` positions, or null
 * when the key is not one the slider handles or nothing would change.
 */
export function sliderIndexAfterKey(key: string, index: number, count: number): number | null {
  const step = STEPS.get(key)
  if (!step || count <= 0) return null
  const last = count - 1
  const next = Math.min(last, Math.max(0, step(index, last)))
  return next === index ? null : next
}
