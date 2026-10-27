import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: process.env.SITE_ENV === 'dev' ? 'https://dev.bonatlas.ru' : 'https://bonatlas.ru',
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
      filter: (page) => !page.includes('/admin') && !page.includes('/cms') && !page.endsWith('/404'),
    }),
  ],
});
