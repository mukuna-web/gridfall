import { useMemo, useState } from 'react'
import type { ClaimEvidence, ClaimResult } from '../lib/claims'
import { claimEvidence, claimVerdict, verdictText } from '../lib/claims'
import type { FlagStore } from '../lib/flags'
import { createBrowserFlagStore } from '../lib/flags'
import { formatDay } from '../lib/format'
import type { CountyIndex } from '../lib/nights'
import { countyLabel } from '../lib/nights'
import type { Claim, IsoDate, NightsByCounty, RestorationByCounty } from '../types'
import { RestorationChart } from './RestorationChart'

interface ClaimCheckProps {
  /** Flags are kept per storm: the same claim id in another export is another claim. */
  readonly stormId: string
  readonly claims: readonly Claim[]
  readonly nights: NightsByCounty
  readonly restoration: RestorationByCounty
  readonly counties: CountyIndex
  readonly landfall: IsoDate
  readonly showOfficial: boolean
  /** Injected in tests; the app uses the browser's localStorage store for this storm. */
  readonly flagStore?: FlagStore
  readonly onShowCounty: (fips: string) => void
}

interface Assessed {
  readonly claim: Claim
  readonly result: ClaimResult
  readonly evidence: ClaimEvidence
}

function pct(share: number): string {
  return `${Math.round(share * 100)}%`
}

/** One plain sentence on why the verdict came out the way it did. */
function explanation({ claim, result, evidence }: Assessed, county: string): string {
  if (evidence.used === null || evidence.peakHi === null || evidence.peakHi <= 0) {
    return `Not enough clear nights in ${county} to compare, so the check stays neutral.`
  }
  const when = evidence.used.day === 0 ? 'the first pass after landfall' : `day ${formatDay(evidence.used.day)}`
  const restored = pct(result.shareRestoredBefore)
  const fell = `the high end of the estimate went from ${pct(evidence.peakHi)} out at its peak to ${pct(evidence.used.hi)} by ${when}`
  if (result.verdict === 'review') {
    return `In ${county}, ${fell}: about ${restored} of the outage was restored before this claim's ${formatDay(claim.claimed_days_out)} days ended. County numbers can't speak for one address, so this asks for a closer look, nothing more.`
  }
  return `In ${county}, ${fell}, about ${restored} restored. A ${formatDay(claim.claimed_days_out)}-day outage fits that curve.`
}

function ClaimPicker({ assessed, value, onChange }: { assessed: readonly Assessed[]; value: string; onChange: (id: string) => void }) {
  const review = assessed.filter((a) => a.result.verdict === 'review')
  const fits = assessed.filter((a) => a.result.verdict === 'fits')
  const option = (a: Assessed) => (
    <option key={a.claim.claim_id} value={a.claim.claim_id}>
      {a.claim.claim_id} · {formatDay(a.claim.claimed_days_out)} days
    </option>
  )
  return (
    <div className="claim-check__picker">
      <label className="label" htmlFor="claim-select">
        Claim
      </label>
      <select id="claim-select" className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {review.length > 0 ? <optgroup label={`Needs review (${review.length})`}>{review.map(option)}</optgroup> : null}
        {fits.length > 0 ? <optgroup label={`Fits (${fits.length})`}>{fits.map(option)}</optgroup> : null}
      </select>
    </div>
  )
}

/** Every claim with its verdict and the nights behind it, recomputed only when the storm data changes. */
function useAssessedClaims(claims: readonly Claim[], nights: NightsByCounty, landfall: IsoDate): Assessed[] {
  return useMemo(
    () =>
      claims.map((claim) => {
        const county = { fips: claim.fips, landfall, nights: nights[claim.fips] ?? [] }
        return {
          claim,
          result: claimVerdict(claim.claimed_days_out, county),
          evidence: claimEvidence(claim.claimed_days_out, county),
        }
      }),
    [claims, nights, landfall],
  )
}

interface FlagState {
  readonly flags: readonly string[]
  /** False when the browser refused storage, so flags last this session only. */
  readonly persistent: boolean
  readonly save: (claimId: string) => void
  readonly clear: (claimId: string) => void
}

/** The review flags, re-read from the store after every change so the page shows what it now holds. */
function useFlags(store: FlagStore): FlagState {
  const [flags, setFlags] = useState<readonly string[]>(() => store.loadFlags())
  // Read after loadFlags above, so it reflects whether that read reached storage.
  const [persistent, setPersistent] = useState(() => store.isPersistent())
  const apply = (change: (claimId: string) => void) => (claimId: string) => {
    change(claimId)
    setFlags(store.loadFlags())
    setPersistent(store.isPersistent())
  }
  return { flags, persistent, save: apply(store.saveFlag), clear: apply(store.clearFlag) }
}

interface ClaimFactsProps {
  readonly claim: Claim
  readonly county: string
  /** False when the claim's county is not among this storm's shapes, so the map cannot show it. */
  readonly onMap: boolean
  readonly onShowCounty: (fips: string) => void
}

function ClaimFacts({ claim, county, onMap, onShowCounty }: ClaimFactsProps) {
  return (
    <dl className="claim-check__facts">
      <div>
        <dt className="label">Policy</dt>
        <dd className="num">{claim.policy_id}</dd>
      </div>
      <div>
        <dt className="label">County</dt>
        <dd>
          {county}{' '}
          <button
            type="button"
            className="text-button"
            disabled={!onMap}
            onClick={() => onShowCounty(claim.fips)}
            aria-label={`Show on map: ${county}`}
          >
            Show on map
          </button>
          {onMap ? null : <span className="claim-check__aside"> (not among this storm's county shapes)</span>}
        </dd>
      </div>
      <div>
        <dt className="label">Claimed outage</dt>
        <dd className="num">{formatDay(claim.claimed_days_out)} days</dd>
      </div>
    </dl>
  )
}

function FlagRow({ claimId, state }: { claimId: string; state: FlagState }) {
  return (
    <div className="flag-row">
      {state.flags.includes(claimId) ? (
        <>
          <p className="flag-row__status" role="status">
            Flagged for review
          </p>
          <button type="button" className="text-button" onClick={() => state.clear(claimId)}>
            Remove flag
          </button>
        </>
      ) : (
        <button type="button" className="button button--flag" onClick={() => state.save(claimId)}>
          Flag for review
        </button>
      )}
      <span className="flag-row__note">
        {state.persistent
          ? `${state.flags.length} flagged for this storm in this browser`
          : 'Saved for this session only: the browser blocked storage'}
      </span>
    </div>
  )
}

/**
 * Pick a synthetic claim, see it against the county's restoration curve,
 * flag it for review. The parent remounts it per storm (StormReport is
 * keyed by storm id), so the flag store is created once per storm.
 */
export function ClaimCheck({
  stormId,
  claims,
  nights,
  restoration,
  counties,
  landfall,
  showOfficial,
  flagStore,
  onShowCounty,
}: ClaimCheckProps) {
  const assessed = useAssessedClaims(claims, nights, landfall)
  // Open on the first claim that needs a look: that is the triage job.
  const [selectedId, setSelectedId] = useState<string>(
    () => (assessed.find((a) => a.result.verdict === 'review') ?? assessed[0])?.claim.claim_id ?? '',
  )
  const store = useMemo(() => flagStore ?? createBrowserFlagStore(stormId), [flagStore, stormId])
  const flags = useFlags(store)

  const current = assessed.find((a) => a.claim.claim_id === selectedId) ?? assessed[0]
  if (!current) return <p className="empty-note">No synthetic claims were exported for this storm.</p>
  const { claim, result, evidence } = current
  const county = countyLabel(counties, claim.fips)

  return (
    <div className="claim-check">
      <div className="claim-check__controls">
        <ClaimPicker assessed={assessed} value={claim.claim_id} onChange={setSelectedId} />
        <ClaimFacts claim={claim} county={county} onMap={Object.hasOwn(counties, claim.fips)} onShowCounty={onShowCounty} />
      </div>
      <RestorationChart
        title={`Restoration curve for ${county}`}
        nights={nights[claim.fips] ?? []}
        landfall={landfall}
        claimedDays={claim.claimed_days_out}
        verdict={result.verdict}
        peakHi={evidence.peakHi}
        restoration={restoration[claim.fips] ?? null}
        showOfficial={showOfficial}
      />
      <div className={`verdict verdict--${result.verdict}`}>
        <p className="verdict__text" data-testid="claim-verdict">
          {verdictText(result)}
        </p>
        <p className="verdict__why">{explanation(current, county)}</p>
      </div>
      <FlagRow claimId={claim.claim_id} state={flags} />
    </div>
  )
}
