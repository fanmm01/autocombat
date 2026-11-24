import path from 'node:path';
import { defineConfig } from 'vite';

export default defineConfig({
  publicDir: 'static',
  resolve: {
    alias: {
      '@shared': path.resolve(__dirname, '../frontend/src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    minify: 'esbuild',
    target: 'es2020',
    lib: {
      entry: path.resolve(__dirname, 'src/game.ts'),
      name: 'AutocombatMiniGame',
      formats: ['iife'],
      fileName: () => 'game.js',
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
      },
    },
  },
});
