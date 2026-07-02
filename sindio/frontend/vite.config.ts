import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, resolve(__dirname), ['VITE_'])
  const apiTarget = env.VITE_API_URL || env.VITE_API_BASE_URL || 'http://localhost:8080'

  return {
    plugins: [react()],
    server: {
      port: 4000,
      host: true,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          ws: true,
        },
        '/health': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            'deck-gl': ['@deck.gl/react', '@deck.gl/layers', '@deck.gl/aggregation-layers'],
            maplibre: ['maplibre-gl'],
            recharts: ['recharts'],
          },
        },
      },
    },
  }
})
