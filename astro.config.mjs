import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://bonatlas.ru',
  output: 'static',
  trailingSlash: 'never',
  server: {
    host: true,
    port: 4321,
  },
  preview: {
    host: true,
    port: 4321,
  },
  integrations: [
    sitemap({
      filter: (page) => !page.includes('/admin') && !page.endsWith('/404'),
    }),
  ],
});
