import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
  test: {
    coverage: {
      provider: 'v8',
      include: ['src/sessionPolicy.ts', 'src/uiPolicy.ts', 'src/uploadPause.ts'],
      thresholds: { lines: 80, functions: 80, branches: 70, statements: 80 },
    },
  },
})
