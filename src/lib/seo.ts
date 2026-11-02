export function canonicalPath(pathname: string): string {
  if (pathname === '/' || /\.[a-z0-9]+$/i.test(pathname)) return pathname;
  return `${pathname.replace(/\/+$/, '')}/`;
}

export function jsonLd(value: unknown): string {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}
