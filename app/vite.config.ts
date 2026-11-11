import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The app is a static folder with no server and no client routing, so a
// relative base lets the same build run from any sub-path (or a file share).
// MapLibre is lazy-loaded into its own chunk; that chunk is ~1 MB minified,
// so the warning limit is raised for it rather than silenced globally.
//
// `vite build --mode e2e` serves the small data set that
// scripts/prepare-e2e-data.mjs assembles, never public/data, so the browser
// tests cannot depend on a lockbox export.
export default defineConfig(({ mode }) => ({
  base: './',
  publicDir: mode === 'e2e' ? '.e2e/public' : 'public',
  plugins: [react()],
  build: {
    target: 'es2022',
    chunkSizeWarningLimit: 1200,
  },
}))
