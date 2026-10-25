// Records the banner frame by frame in headless Chromium.
//
//   npm run record                  every frame of the loop  -> .frames/0000.png ...
//   npm run stills -- 0.5 2.6 4.9   single moments          -> .frames/stills/t4.90.png ...
//   npm run serve                   the live page on http://127.0.0.1:8173/
//
// Frames are 1800×600 (2× pixels, for encode.py to shrink). FPS=20 changes the frame rate; HEADED=1 uses a visible browser (your GPU) if WebGL fails headless.

import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const here = dirname(fileURLToPath(import.meta.url));
const site = join(here, 'site');
const out = join(here, '.frames');
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8' };

const [mode = '--record', ...rest] = process.argv.slice(2);

const server = createServer(async (req, res) => {
  const path = new URL(req.url, 'http://local').pathname;
  const file = resolve(site, `.${path === '/' ? '/index.html' : path}`);
  if (!file.startsWith(site)) return res.writeHead(403).end();
  try {
    const body = await readFile(file);
    res.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream' }).end(body);
  } catch {
    res.writeHead(404).end();
  }
});
await new Promise((done) => server.listen(mode === '--serve' ? 8173 : 0, '127.0.0.1', done));
const origin = `http://127.0.0.1:${server.address().port}`;

if (mode === '--serve') {
  console.log(`Live page: ${origin}/   (Ctrl+C to stop)`);
} else {
  const headless = !process.env.HEADED;
  const browser = await chromium.launch({
    headless,
    args: headless ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] : [],
  });
  const page = await browser.newPage({ viewport: { width: 900, height: 300 }, deviceScaleFactor: 2 });
  page.on('console', (m) => ['error', 'warning'].includes(m.type()) && console.log(`[page] ${m.text()}`));
  page.on('pageerror', (e) => console.error(`[page error] ${e.message}`));
  await page.goto(`${origin}/index.html?record`);
  await page.waitForFunction(() => window.banner, null, { timeout: 60_000 });
  await page.evaluate(() => window.banner.ready);
  const duration = await page.evaluate(() => window.banner.duration);
  const fps = Number(process.env.FPS ?? (await page.evaluate(() => window.banner.fps)));

  const shoot = async (t, path) => {
    await page.evaluate((time) => window.banner.render(time), t);
    await page.screenshot({ path });
  };

  if (mode === '--stills') {
    await mkdir(join(out, 'stills'), { recursive: true });
    for (const t of rest.map(Number)) {
      const path = join(out, 'stills', `t${t.toFixed(2)}.png`);
      await shoot(t, path);
      console.log(path);
    }
  } else {
    await rm(out, { recursive: true, force: true });
    await mkdir(out, { recursive: true });
    const n = Math.round(duration * fps);
    const started = Date.now();
    for (let i = 0; i < n; i++) {
      await shoot(i / fps, join(out, `${String(i).padStart(4, '0')}.png`));
      if (i % 24 === 0) console.log(`frame ${i}/${n}  ${((Date.now() - started) / 1000).toFixed(0)} s`);
    }
    await writeFile(join(out, 'meta.json'), JSON.stringify({ fps, duration, frames: n }));
    console.log(`${n} frames at ${fps} fps in ${out}`);
  }
  await browser.close();
  server.close();
}
