import { fileURLToPath } from 'node:url'
import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

// happy-dom, not jsdom: jsdom hung vitest's workers on the machine this was built on.
// maplibre-gl needs WebGL, so tests get a small stub; only the bare package
// name is aliased, so the worker `?url` import still resolves to the real file.
export default mergeConfig(
  viteConfig({ command: 'serve', mode: 'test' }),
  defineConfig({
    resolve: {
      alias: [
        {
          find: /^maplibre-gl$/,
          replacement: fileURLToPath(new URL('./src/test/maplibre-stub.ts', import.meta.url)),
        },
      ],
    },
    test: {
      environment: 'happy-dom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}'],
      css: false,
      restoreMocks: true,
      unstubGlobals: true,
    },
  }),
)
