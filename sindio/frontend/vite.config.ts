import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 4000,
    host: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_URL || 'http://localhost:8080',
        changeOrigin: true,
        ws: true,
      },
      '/health': {
        target: process.env.VITE_API_URL || 'http://localhost:8080',
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
})
