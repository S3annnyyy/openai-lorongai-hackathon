#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { parseArgs, ensureAbsolutePath } from './arg-utils.mjs';

const require = createRequire(import.meta.url);

async function importPlaywright() {
  try {
    return await import('playwright');
  } catch {
    return null;
  }
}

function readDashboard(source) {
  const dashboardPath = path.join(source, 'dashboard_state.json');
  if (!fs.existsSync(dashboardPath)) {
    throw new Error(`dashboard_state.json missing at ${dashboardPath}`);
  }
  const text = fs.readFileSync(dashboardPath, 'utf8');
  return JSON.parse(text);
}

async function screenshotMermaid(page, mermaidPath, title, diagram, outPath) {
  await page.setViewportSize({ width: 1680, height: 980 });
  await page.setContent('<main><h1 id="title"></h1><div id="graph"></div></main>');
  await page.addStyleTag({
    content: `
      body { margin: 0; padding: 28px; font-family: "IBM Plex Sans", "Segoe UI", sans-serif; background: #f8fafc; }
      main { background: white; border: 1px solid #cbd5e1; border-radius: 12px; padding: 20px; }
      h1 { margin-top: 0; font-size: 30px; }
      svg { max-width: 100%; }
    `
  });
  await page.addScriptTag({ path: mermaidPath });
  await page.evaluate(async ({ titleText, graphText }) => {
    // @ts-ignore
    mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' });
    // @ts-ignore
    const rendered = await mermaid.render(`img_${Date.now()}`, graphText);
    const titleEl = document.getElementById('title');
    const graphEl = document.getElementById('graph');
    if (titleEl) titleEl.textContent = titleText;
    if (graphEl) graphEl.innerHTML = rendered.svg;
  }, { titleText: title, graphText: diagram });
  await page.screenshot({ path: outPath, fullPage: true });
}

async function screenshotOnboarding(page, dashboard, outPath) {
  await page.setViewportSize({ width: 1680, height: 980 });
  const startHere = dashboard?.onboarding?.start_here || [];
  const flows = dashboard?.onboarding?.key_flows || [];

  const rows = startHere.map((item, index) => `<li><strong>${index + 1}.</strong> <code>${item}</code></li>`).join('');
  const flowRows = flows
    .map((flow) => `<li><strong>${flow.name}</strong>: ${flow.flow}</li>`)
    .join('');

  await page.setContent(`
    <main>
      <h1>Onboarding Map</h1>
      <section>
        <h2>Start Here</h2>
        <ol>${rows || '<li>No start path detected</li>'}</ol>
      </section>
      <section>
        <h2>Key Flows</h2>
        <ul>${flowRows || '<li>No flows detected</li>'}</ul>
      </section>
      <p class="kiv">3D graph is KIV (Phase 2).</p>
    </main>
  `);
  await page.addStyleTag({
    content: `
      body { margin: 0; padding: 28px; font-family: "IBM Plex Sans", "Segoe UI", sans-serif; background: #f8fafc; color: #0f172a; }
      main { background: white; border: 1px solid #cbd5e1; border-radius: 12px; padding: 20px; }
      h1 { margin-top: 0; }
      code { background: #e2e8f0; padding: 2px 6px; border-radius: 6px; }
      .kiv { margin-top: 20px; color: #9a3412; font-weight: 600; }
    `
  });
  await page.screenshot({ path: outPath, fullPage: true });
}

async function main() {
  const args = parseArgs();
  const source = ensureAbsolutePath(args.source, process.cwd());
  const target = ensureAbsolutePath(args.target, process.cwd());

  if (!source || !target) {
    console.log('Usage: node scripts/export-images.mjs --source <output_root> --target <images_dir>');
    process.exit(1);
  }

  let dashboard;
  try {
    dashboard = readDashboard(source);
  } catch (error) {
    console.log(`PNG export skipped: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(0);
  }

  const playwright = await importPlaywright();
  if (!playwright) {
    console.log('PNG export skipped: playwright is not installed. Run npm install in code-autopsy/viewer.');
    process.exit(0);
  }

  let mermaidPath;
  try {
    mermaidPath = require.resolve('mermaid/dist/mermaid.min.js');
  } catch {
    console.log('PNG export skipped: mermaid dependency missing. Run npm install in code-autopsy/viewer.');
    process.exit(0);
  }

  fs.mkdirSync(target, { recursive: true });

  const browser = await playwright.chromium.launch({ headless: true });
  const page = await browser.newPage();

  const map = [
    ['architecture-services', dashboard?.diagrams?.architecture_services || dashboard?.diagrams?.architecture || 'flowchart LR\nA-->B\n', 'architecture.png'],
    ['architecture-code', dashboard?.diagrams?.architecture_code || dashboard?.diagrams?.architecture_services || dashboard?.diagrams?.architecture || 'flowchart LR\nA-->B\n', 'architecture-code.png'],
    ['architecture-iac', dashboard?.diagrams?.architecture_iac || 'flowchart LR\nA-->B\n', 'architecture-iac.png'],
    ['er', dashboard?.diagrams?.er || 'erDiagram\n', 'er.png'],
    ['call-graph', dashboard?.diagrams?.call_graph || 'flowchart LR\nA-->B\n', 'call-graph.png'],
    ['dependency', dashboard?.diagrams?.dependencies || 'flowchart LR\nA-->B\n', 'dependency.png'],
    ['sequence', dashboard?.diagrams?.sequence || 'sequenceDiagram\nA->>B: request\nB-->>A: response\n', 'sequence.png'],
    ['use-case', dashboard?.diagrams?.use_case || 'flowchart LR\nactor_client["User"] --> use_case(["Capability"])\n', 'use-case.png']
  ];

  for (const [title, diagram, filename] of map) {
    const outPath = path.join(target, filename);
    await screenshotMermaid(page, mermaidPath, String(title), String(diagram), outPath);
  }

  await screenshotOnboarding(page, dashboard, path.join(target, 'onboarding.png'));

  await browser.close();
  console.log(`PNG snapshots exported to ${target}`);
}

main().catch((error) => {
  console.log(`PNG export skipped: ${error instanceof Error ? error.message : String(error)}`);
  process.exit(0);
});
