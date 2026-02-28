"use client";

import mermaid from "mermaid";
import { useEffect, useMemo, useState } from "react";

type Props = {
  diagram: string;
  title: string;
  compact?: boolean;
};

export default function MermaidCard({ diagram, title, compact = false }: Props) {
  const [svg, setSvg] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const diagramId = useMemo(
    () => `m_${title.replace(/[^a-zA-Z0-9]/g, "_")}_${Math.random().toString(16).slice(2)}`,
    [title]
  );
  const safeTitle = useMemo(() => title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, ""), [title]);
  const canDownload = svg.includes("<svg");

  useEffect(() => {
    let active = true;

    async function render() {
      try {
        mermaid.initialize({
          startOnLoad: false,
          theme: "default",
          securityLevel: "loose",
          fontFamily: "IBM Plex Sans"
        });
        const rendered = await mermaid.render(diagramId, diagram || "flowchart LR\\nA-->B");
        if (active) {
          setSvg(rendered.svg);
        }
      } catch (error) {
        if (active) {
          const message = error instanceof Error ? error.message : String(error);
          setSvg(`<pre>Mermaid render error: ${message}</pre>`);
        }
      }
    }

    render();

    return () => {
      active = false;
    };
  }, [diagram, diagramId]);

  async function copySource() {
    try {
      await navigator.clipboard.writeText(diagram);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  function downloadSvg() {
    if (!canDownload) return;
    const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${safeTitle || "diagram"}.svg`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="panel">
      <div className="diagram-header">
        <h2>{title}</h2>
        <div className="diagram-toolbar">
          <button className="tool-btn" onClick={copySource} type="button">
            {copied ? "Copied" : "Copy Mermaid"}
          </button>
          <button className="tool-btn" onClick={downloadSvg} type="button" disabled={!canDownload}>
            Download SVG
          </button>
        </div>
      </div>
      <div className={`mermaid-shell ${compact ? "compact" : ""}`} dangerouslySetInnerHTML={{ __html: svg }} />
      <details className="diagram-raw">
        <summary>View Mermaid source</summary>
        <pre>{diagram}</pre>
      </details>
    </div>
  );
}
