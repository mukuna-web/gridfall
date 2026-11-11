# Test fixtures: SYNTHETIC data only

Everything under this folder is invented for unit tests. Nothing here comes from
EAGLE-I, Black Marble, the Census, or any pipeline output.

- `index.json` mirrors `public/data/index.json` (one storm).
- `milton/` mirrors `public/data/milton2024/`. It uses the id `milton2024` only so
  the loader test walks the same path a lockbox storm will. See `milton/README.md`.
