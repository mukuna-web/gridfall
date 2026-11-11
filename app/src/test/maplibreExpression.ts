/**
 * A small evaluator for the MapLibre style expressions StormMap writes, so
 * tests can ask "what colour does a county with this feature state get?"
 * instead of pattern-matching the expression's shape. It covers only the
 * operators the map uses and throws on anything else, so a new operator in
 * StormMap shows up here as a clear failure rather than a silent pass.
 */
import { hexToRgb } from '../lib/color'

export type FeatureState = Readonly<Record<string, unknown>>

function mixHex(a: string, b: string, f: number): string {
  const ca = hexToRgb(a)
  const cb = hexToRgb(b)
  const channel = (i: 0 | 1 | 2) => Math.round(ca[i] + (cb[i] - ca[i]) * f)
  return `#${[channel(0), channel(1), channel(2)].map((c) => c.toString(16).padStart(2, '0')).join('')}`
}

function interpolate(args: readonly unknown[], state: FeatureState): unknown {
  const [kind, inputExpr, ...stops] = args
  if (!Array.isArray(kind) || kind[0] !== 'linear') throw new Error(`only linear interpolation is supported, got ${JSON.stringify(kind)}`)
  const input = evaluate(inputExpr, state)
  if (typeof input !== 'number' || !Number.isFinite(input)) {
    throw new Error(`interpolate needs a finite number, got ${String(input)}`)
  }
  const pairs: Array<[number, string]> = []
  for (let i = 0; i + 1 < stops.length; i += 2) pairs.push([stops[i] as number, stops[i + 1] as string])
  const first = pairs[0]
  const last = pairs[pairs.length - 1]
  if (!first || !last) throw new Error('interpolate needs at least one stop')
  if (input <= first[0]) return first[1]
  if (input >= last[0]) return last[1]
  for (let i = 0; i + 1 < pairs.length; i += 1) {
    const [lowAt, lowColor] = pairs[i] as [number, string]
    const [highAt, highColor] = pairs[i + 1] as [number, string]
    if (input >= lowAt && input <= highAt) return mixHex(lowColor, highColor, (input - lowAt) / (highAt - lowAt))
  }
  throw new Error('unreachable: input outside every stop pair')
}

/** Evaluates a style expression against one feature's state. */
export function evaluate(expr: unknown, state: FeatureState): unknown {
  if (!Array.isArray(expr)) return expr
  const [op, ...args] = expr as [string, ...unknown[]]
  switch (op) {
    case 'feature-state':
      return state[args[0] as string] ?? null
    case 'boolean': {
      for (const arg of args) {
        const value = evaluate(arg, state)
        if (typeof value === 'boolean') return value
      }
      throw new Error('boolean: no boolean value among the arguments')
    }
    case '==':
      return evaluate(args[0], state) === evaluate(args[1], state)
    case 'case': {
      for (let i = 0; i + 1 < args.length; i += 2) {
        if (evaluate(args[i], state) === true) return evaluate(args[i + 1], state)
      }
      return evaluate(args[args.length - 1], state)
    }
    case 'interpolate':
      return interpolate(args, state)
    default:
      throw new Error(`unsupported expression operator ${JSON.stringify(op)}; extend maplibreExpression.ts`)
  }
}
