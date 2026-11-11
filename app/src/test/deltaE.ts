/**
 * CIEDE2000 colour difference (Sharma, Wu and Dalal, 2005), for tests that
 * ask whether two colours are distinguishable, such as a hatch tile's mean
 * colour against the ramp's 0% colour. sRGB in, D65 white point.
 */

export type Rgb = readonly [number, number, number]
export type Lab = readonly [L: number, a: number, b: number]

const EPSILON = 216 / 24389
const KAPPA = 24389 / 27

function srgbToLinear(channel: number): number {
  const s = channel / 255
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
}

export function rgbToLab([r, g, b]: Rgb): Lab {
  const [R, G, B] = [srgbToLinear(r), srgbToLinear(g), srgbToLinear(b)]
  const x = (0.4124564 * R + 0.3575761 * G + 0.1804375 * B) / 0.95047
  const y = 0.2126729 * R + 0.7151522 * G + 0.072175 * B
  const z = (0.0193339 * R + 0.119192 * G + 0.9503041 * B) / 1.08883
  const f = (t: number) => (t > EPSILON ? Math.cbrt(t) : (KAPPA * t + 16) / 116)
  const [fx, fy, fz] = [f(x), f(y), f(z)]
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)]
}

const rad = (deg: number) => (deg * Math.PI) / 180
const deg = (r: number) => (r * 180) / Math.PI

function hueDegrees(a: number, b: number): number {
  if (a === 0 && b === 0) return 0
  const h = deg(Math.atan2(b, a))
  return h < 0 ? h + 360 : h
}

function hueDifference(h1: number, h2: number, chromaProduct: number): number {
  if (chromaProduct === 0) return 0
  const d = h2 - h1
  if (Math.abs(d) <= 180) return d
  return d > 180 ? d - 360 : d + 360
}

function meanHue(h1: number, h2: number, chromaProduct: number): number {
  if (chromaProduct === 0) return h1 + h2
  if (Math.abs(h1 - h2) <= 180) return (h1 + h2) / 2
  return h1 + h2 < 360 ? (h1 + h2 + 360) / 2 : (h1 + h2 - 360) / 2
}

export function deltaE2000([L1, a1, b1]: Lab, [L2, a2, b2]: Lab): number {
  const meanC = (Math.hypot(a1, b1) + Math.hypot(a2, b2)) / 2
  const g = 0.5 * (1 - Math.sqrt(meanC ** 7 / (meanC ** 7 + 25 ** 7)))
  const a1p = (1 + g) * a1
  const a2p = (1 + g) * a2
  const c1p = Math.hypot(a1p, b1)
  const c2p = Math.hypot(a2p, b2)
  const h1p = hueDegrees(a1p, b1)
  const h2p = hueDegrees(a2p, b2)
  const chromaProduct = c1p * c2p

  const dL = L2 - L1
  const dC = c2p - c1p
  const dH = 2 * Math.sqrt(chromaProduct) * Math.sin(rad(hueDifference(h1p, h2p, chromaProduct) / 2))

  const meanL = (L1 + L2) / 2
  const meanCp = (c1p + c2p) / 2
  const meanH = meanHue(h1p, h2p, chromaProduct)
  const t =
    1 - 0.17 * Math.cos(rad(meanH - 30)) + 0.24 * Math.cos(rad(2 * meanH)) + 0.32 * Math.cos(rad(3 * meanH + 6)) - 0.2 * Math.cos(rad(4 * meanH - 63))
  const dTheta = 30 * Math.exp(-(((meanH - 275) / 25) ** 2))
  const rc = 2 * Math.sqrt(meanCp ** 7 / (meanCp ** 7 + 25 ** 7))
  const sl = 1 + (0.015 * (meanL - 50) ** 2) / Math.sqrt(20 + (meanL - 50) ** 2)
  const sc = 1 + 0.045 * meanCp
  const sh = 1 + 0.015 * meanCp * t
  const rt = -Math.sin(rad(2 * dTheta)) * rc

  const l = dL / sl
  const c = dC / sc
  const h = dH / sh
  return Math.sqrt(l * l + c * c + h * h + rt * c * h)
}

export function deltaE2000Rgb(a: Rgb, b: Rgb): number {
  return deltaE2000(rgbToLab(a), rgbToLab(b))
}
