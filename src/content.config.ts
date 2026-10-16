import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const blog = defineCollection({
  loader: glob({ pattern: '**/*.{md,mdx}', base: './src/content/blog' }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    slug: z.string(),
    category: z.enum(['Карты', 'Писательская работа', 'Персонажи', 'Сюжет', 'Создание миров']),
    author: z.string(),
    publishedAt: z.coerce.date(),
    updatedAt: z.coerce.date().optional(),
    draft: z.boolean().default(true),
    image: z.string().optional(),
    imageAlt: z.string().optional(),
    related: z.array(z.string()).optional(),
  }),
});

export const collections = { blog };
