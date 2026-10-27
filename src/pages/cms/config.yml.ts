import config from '../../../public/admin/config.yml?raw';

export function GET() {
  const isDev = process.env.SITE_ENV === 'dev';
  // Host-Lite has no media-upload API. Files are delivered separately over FTPS;
  // editors paste URLs instead of silently committing binaries to Git.
  const environmentConfig = config
    .replace(/^  branch: .*$/m, `  branch: ${isDev ? 'develop' : 'main'}`)
    .replace(/^app_title: .*$/m, `app_title: BON — ${isDev ? 'DEV / проверочная версия' : 'PROD / основной сайт'}`)
    .replace(/^\s*(media_folder|public_folder):.*\r?\n/gm, '\n')
    .replace(/widget: image/g, 'widget: string');
  // Sveltia validates media_folder even when all media widgets are URL fields.
  // Keep the required declaration but disable its internal Git media provider.
  const configured = `media_folder: public/uploads\nmedia_libraries:\n  default: false\n${environmentConfig}`;
  return new Response(configured, {
    headers: { 'Content-Type': 'application/yaml; charset=utf-8' },
  });
}
