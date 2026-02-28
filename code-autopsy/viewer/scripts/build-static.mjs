#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { parseArgs, ensureAbsolutePath } from './arg-utils.mjs';

function writeFallback(target, source) {
  fs.rmSync(target, { recursive: true, force: true });
  fs.mkdirSync(target, { recursive: true });
  const html = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Code Autopsy Viewer (Fallback)</title>
    <style>
      body { font-family: "IBM Plex Sans", "Segoe UI", sans-serif; margin: 0; padding: 24px; background: #f8fafc; color: #0f172a; }
      .card { background: white; border: 1px solid #cbd5e1; border-radius: 12px; padding: 18px; max-width: 900px; }
      a { color: #1d4ed8; }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>Code Autopsy Viewer</h1>
      <p>Next.js static export was not generated on this machine.</p>
      <p>Install dependencies and run <code>npm run build:embed -- --source ${source} --target ${target}</code>.</p>
      <p>You can still open the generated docs and Mermaid files from the output folder.</p>
    </div>
  </body>
</html>`;
  fs.writeFileSync(path.join(target, 'index.html'), html, 'utf8');
}

function copyDashboard(source, viewerRoot) {
  const dashboardPath = path.join(source, 'dashboard_state.json');
  const destination = path.join(viewerRoot, 'public', 'data', 'latest', 'dashboard_state.json');
  fs.mkdirSync(path.dirname(destination), { recursive: true });

  if (!fs.existsSync(dashboardPath)) {
    throw new Error(`dashboard_state.json not found at ${dashboardPath}`);
  }
  fs.copyFileSync(dashboardPath, destination);
}

function listFilesRecursively(rootDir) {
  const files = [];
  const stack = [rootDir];
  while (stack.length > 0) {
    const current = stack.pop();
    const entries = fs.readdirSync(current, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        stack.push(fullPath);
      } else if (entry.isFile()) {
        files.push(fullPath);
      }
    }
  }
  return files;
}

function normalizeStaticAssetPaths(targetDir) {
  const files = listFilesRecursively(targetDir).filter((file) => file.endsWith('.html'));
  for (const filePath of files) {
    const source = fs.readFileSync(filePath, 'utf8');
    const updated = source.replace(/(["'])\/_next\//g, '$1./_next/');
    if (updated !== source) {
      fs.writeFileSync(filePath, updated, 'utf8');
    }
  }
}

function main() {
  const args = parseArgs();
  const viewerRoot = path.resolve(path.join(path.dirname(fileURLToPath(import.meta.url)), '..'));
  const source = ensureAbsolutePath(args.source, process.cwd());
  const target = ensureAbsolutePath(args.target, process.cwd());

  if (!source || !target) {
    console.log('Usage: node scripts/build-static.mjs --source <output_root> --target <viewer_static_output>');
    process.exit(1);
  }

  try {
    copyDashboard(source, viewerRoot);
  } catch (error) {
    writeFallback(target, source);
    console.log(`Viewer fallback created: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(0);
  }

  if (!fs.existsSync(path.join(viewerRoot, 'node_modules'))) {
    writeFallback(target, source);
    console.log('Viewer fallback created: dependencies missing. Run npm install in code-autopsy/viewer.');
    process.exit(0);
  }

  const exportResult = spawnSync('npm', ['run', 'export'], {
    cwd: viewerRoot,
    stdio: 'inherit',
    shell: process.platform === 'win32'
  });

  if (exportResult.status !== 0) {
    writeFallback(target, source);
    console.log('Viewer fallback created: Next.js export failed.');
    process.exit(0);
  }

  const outDir = path.join(viewerRoot, 'out');
  if (!fs.existsSync(outDir)) {
    writeFallback(target, source);
    console.log('Viewer fallback created: Next.js output folder missing.');
    process.exit(0);
  }

  fs.rmSync(target, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.cpSync(outDir, target, { recursive: true });
  normalizeStaticAssetPaths(target);

  console.log(`Viewer exported to ${target}`);
}

main();
