import { readFile } from 'node:fs/promises';
import { join } from 'node:path';

// The kit builder's data, served byte for byte from site/: sources.json, kit.json (which the kit's program reads
// there too) and regions.json, all written by site/build_sources.py. Any other name is a 404.
const FILES = ['kit.json', 'sources.json', 'regions.json'];

export const dynamic = 'force-static';
export const dynamicParams = false;
export function generateStaticParams() {
  return FILES.map((file) => ({ file }));
}

export async function GET(request, { params }) {
  const { file } = await params;
  return new Response(await readFile(join(process.cwd(), file)), { headers: { 'Content-Type': 'application/json' } });
}
