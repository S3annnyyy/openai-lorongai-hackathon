import { NextResponse } from "next/server";

const DEFAULT_PLANTUML_SERVER = "https://www.plantuml.com/plantuml";
const MAX_SOURCE_BYTES = 1_500_000;
const REQUEST_TIMEOUT_MS = 20_000;

function getPlantUmlServerBase(): string {
  const configured = process.env.PLANTUML_SERVER_URL || process.env.NEXT_PUBLIC_PLANTUML_SERVER_URL;
  return (configured || DEFAULT_PLANTUML_SERVER).trim().replace(/\/+$/, "");
}

function mapUmlToSvg(location: string, serverBase: string): string {
  const absolute = new URL(location, `${serverBase}/`);
  absolute.pathname = absolute.pathname.replace(/\/uml\//, "/svg/");
  return absolute.toString();
}

function createTimeoutController(timeoutMs: number): AbortController {
  const controller = new AbortController();
  setTimeout(() => controller.abort(), timeoutMs);
  return controller;
}

export async function POST(request: Request) {
  let source = "";
  try {
    const body = (await request.json()) as { source?: string };
    source = typeof body.source === "string" ? body.source : "";
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  if (!source.trim()) {
    return NextResponse.json({ error: "PlantUML source is required." }, { status: 400 });
  }

  const sourceBytes = new TextEncoder().encode(source).byteLength;
  if (sourceBytes > MAX_SOURCE_BYTES) {
    return NextResponse.json(
      { error: `PlantUML source too large (${sourceBytes} bytes).` },
      { status: 413 }
    );
  }

  const serverBase = getPlantUmlServerBase();

  try {
    const postController = createTimeoutController(REQUEST_TIMEOUT_MS);
    const postResp = await fetch(`${serverBase}/svg`, {
      method: "POST",
      headers: { "content-type": "text/plain; charset=utf-8" },
      body: source,
      redirect: "manual",
      signal: postController.signal,
      cache: "no-store",
    });

    let svgResponse: Response;
    const location = postResp.headers.get("location");
    if (location) {
      const svgUrl = mapUmlToSvg(location, serverBase);
      const getController = createTimeoutController(REQUEST_TIMEOUT_MS);
      svgResponse = await fetch(svgUrl, {
        method: "GET",
        headers: { accept: "image/svg+xml,text/plain;q=0.9,*/*;q=0.8" },
        signal: getController.signal,
        cache: "no-store",
      });
    } else if (postResp.ok) {
      svgResponse = postResp;
    } else {
      return NextResponse.json(
        { error: `PlantUML POST failed with status ${postResp.status}.` },
        { status: 502 }
      );
    }

    if (!svgResponse.ok) {
      return NextResponse.json(
        { error: `PlantUML SVG fetch failed with status ${svgResponse.status}.` },
        { status: 502 }
      );
    }

    const svg = await svgResponse.text();
    if (!svg.includes("<svg")) {
      return NextResponse.json(
        { error: "PlantUML response did not contain SVG output." },
        { status: 502 }
      );
    }

    return new Response(svg, {
      status: 200,
      headers: {
        "content-type": "image/svg+xml; charset=utf-8",
        "cache-control": "no-store",
        "x-plantuml-server": serverBase,
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return NextResponse.json(
      { error: `PlantUML render request failed (${message}).` },
      { status: 502 }
    );
  }
}
