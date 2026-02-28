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

function sanitizeRepo(value: string): string {
  return value.replace(/[^a-zA-Z0-9_.-]/g, "");
}

export async function GET(_request: Request, context: { params: { repo: string } }) {
  const repo = sanitizeRepo(context.params.repo || "");
  if (!repo) {
    return NextResponse.json({ error: "Invalid repo name" }, { status: 400 });
  }

  const root = getOutputRoot();
  const dashboardPath = path.join(root, repo, "dashboard_state.json");

  try {
    const payload = await fs.readFile(dashboardPath, "utf-8");
    const parsed = JSON.parse(payload);
    return NextResponse.json(parsed);
  } catch {
    return NextResponse.json(
      {
        error: `dashboard_state.json not found for repo '${repo}'`,
        repo
      },
      { status: 404 }
    );
  }
}
