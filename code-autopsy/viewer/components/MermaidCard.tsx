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
  const diagramId = useMemo(
    () => `m_${title.replace(/[^a-zA-Z0-9]/g, "_")}_${Math.random().toString(16).slice(2)}`,
    [title]
  );

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

  return (
    <div className="panel">
      <h2>{title}</h2>
      <div className={`mermaid-shell ${compact ? "compact" : ""}`} dangerouslySetInnerHTML={{ __html: svg }} />
    </div>
  );
}
