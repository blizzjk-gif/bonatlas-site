import config from '../../../public/admin/config.yml?raw';

export function GET() {
  return new Response(config, {
    headers: { 'Content-Type': 'application/yaml; charset=utf-8' },
  });
}
