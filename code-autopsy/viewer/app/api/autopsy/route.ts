import fs from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";

function getOutputRoot(): string {
  const configured = process.env.AUTOPSY_OUTPUT_ROOT;
  if (configured && configured.trim().length > 0) {
    return path.resolve(configured);
  }
  return path.resolve(process.cwd(), "..", ".autopsy-outputs");
}

async function listRepoDirectories(root: string): Promise<string[]> {
  try {
    const entries = await fs.readdir(root, { withFileTypes: true });
    return entries
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith("_"))
      .map((entry) => entry.name)
      .sort((a, b) => a.localeCompare(b));
  } catch {
    return [];
  }
}

async function selectDefaultRepo(root: string, repos: string[]): Promise<string | null> {
  let latestRepo: string | null = null;
  let latestTime = -1;

  for (const repo of repos) {
    const dashboardPath = path.join(root, repo, "dashboard_state.json");
    try {
      const stat = await fs.stat(dashboardPath);
      const mtime = stat.mtimeMs || 0;
      if (mtime > latestTime) {
        latestTime = mtime;
        latestRepo = repo;
      }
    } catch {
      continue;
    }
  }

  return latestRepo ?? (repos.length > 0 ? repos[0] : null);
}

export async function GET() {
  const root = getOutputRoot();
  const repos = await listRepoDirectories(root);
  const defaultRepo = await selectDefaultRepo(root, repos);
  return NextResponse.json({
    root,
    repos,
    defaultRepo
  });
}
