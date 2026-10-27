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
      filter: (page) => !/^\/(?:admin|cms|404(?:\.html)?)(?:\/|$)/.test(new URL(page).pathname),
    }),
  ],
});
