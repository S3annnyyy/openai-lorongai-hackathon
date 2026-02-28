"use client";

import { useEffect, useState } from "react";

type PlantUmlCardProps = {
  diagram: string;
  title: string;
  rawDocument?: string;
};

const ENCODE_TIMEOUT_MS = 20_000;

export default function PlantUmlCard({ diagram, title, rawDocument }: PlantUmlCardProps) {
  const [svgMarkup, setSvgMarkup] = useState("");
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [serverHint, setServerHint] = useState("");

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const encodeTimeout = setTimeout(() => {
      if (cancelled) return;
      controller.abort();
      setLoading(false);
      setErrorMessage(
        "PlantUML render timed out. Check network access or set PLANTUML_SERVER_URL on the viewer server."
      );
    }, ENCODE_TIMEOUT_MS);

    setLoading(true);
    setErrorMessage("");
    setSvgMarkup("");
    setServerHint("");

    async function renderPlantUml() {
      try {
        const response = await fetch("/api/plantuml", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ source: diagram }),
          cache: "no-store",
          signal: controller.signal,
        });

        if (!response.ok) {
          let detail = `PlantUML render failed (${response.status}).`;
          try {
            const payload = (await response.json()) as { error?: string };
            if (payload?.error) {
              detail = payload.error;
            }
          } catch {
            // Keep default detail.
          }
          throw new Error(detail);
        }

        const svg = await response.text();
        if (!svg.includes("<svg")) {
          throw new Error("Rendered response did not contain SVG.");
        }
        if (cancelled) return;
        setSvgMarkup(svg);
        const renderServer = response.headers.get("x-plantuml-server");
        if (renderServer) {
          setServerHint(renderServer);
        }
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error);
        setErrorMessage(`Unable to render PlantUML (${message}).`);
      } finally {
        clearTimeout(encodeTimeout);
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    renderPlantUml();
    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(encodeTimeout);
    };
  }, [diagram]);

  return (
    <div className="panel">
      <div className="diagram-header">
        <h2>{title}</h2>
        <span className="zoom-level">PlantUML</span>
      </div>
      <div className="mermaid-shell expanded plantuml-shell">
        {loading ? (
          <p className="muted">Rendering data diagram...</p>
        ) : null}
        {!loading && svgMarkup && !errorMessage ? (
          <div className="plantuml-image" dangerouslySetInnerHTML={{ __html: svgMarkup }} />
        ) : null}
      </div>
      {errorMessage ? (
        <p className="note">{errorMessage}</p>
      ) : (
        <p className="muted">
          Rendered via <code>/api/plantuml</code>
          {serverHint ? (
            <>
              {" "}using <code>{serverHint}</code>
            </>
          ) : null}
          .
        </p>
      )}
      <details className="diagram-raw">
        <summary>View PlantUML source</summary>
        <pre>{diagram}</pre>
      </details>
      {rawDocument ? (
        <details className="diagram-raw">
          <summary>View raw data document</summary>
          <pre>{rawDocument}</pre>
        </details>
      ) : null}
    </div>
  );
}
