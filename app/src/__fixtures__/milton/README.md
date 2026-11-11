# Synthetic "Milton" fixture: NOT real Milton data

**Every number in this folder is made up.** It exists so `loadStorm parses the
Milton fixture` can exercise the loader without touching the lockbox.

- The four counties (Alpha, Bravo, Charlie, Delta), their state `ZZ`, their FIPS
  codes (`99001`-`99007`) and their square shapes do not exist.
- Night estimates, ranges, "official" values, restoration days, policy counts and
  claims are hand-written test values. They were not derived from EAGLE-I, Black
  Marble, or any file under `data/`.
- The scorecard uses deliberately fake repeating values (11.1, 22.2, 111111 ...)
  so nobody can mistake it for a result.
- Only the storm id, name and landfall date (public facts from
  `config/storms.yaml`) are real.

Never replace these values with real Milton or Helene numbers: those storms stay
locked until the pass-bar commit (docs/plan.md, Task 9).
