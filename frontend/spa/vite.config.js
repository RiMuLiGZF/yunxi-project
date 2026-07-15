import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8008',
        changeOrigin: true,
      },
      '/m8': {
        target: 'http://localhost:8008',
        changeOrigin: true,
      },
      '/m4': {
        target: 'http://localhost:8004',
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': '/src',
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
})
