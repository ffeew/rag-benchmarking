import { defineConfig } from 'vite'
import { TanStackRouterVite } from '@tanstack/router-plugin/vite'

import viteReact, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'

const config = defineConfig({
  resolve: { tsconfigPaths: true },
  plugins: [
    TanStackRouterVite({ target: 'react', autoCodeSplitting: false }),
    tailwindcss(),
    viteReact(),
    babel({ presets: [reactCompilerPreset()] }),
  ],
})

export default config
