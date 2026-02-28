"use client";

import mermaid from "mermaid";
import { useEffect, useMemo, useState } from "react";

type Props = {
  diagram: string;
  title: string;
  compact?: boolean;
};

type IconName = "copy" | "download" | "close" | "check";

function Icon({ name }: { name: IconName }) {
  if (name === "copy") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="9" y="9" width="11" height="11" rx="2" />
        <rect x="4" y="4" width="11" height="11" rx="2" />
      </svg>
    );
  }
  if (name === "download") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 4v11M8 11l4 4 4-4M5 20h14" />
      </svg>
    );
  }
  if (name === "close") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="m6 6 12 12M18 6 6 18" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m5 12 5 5 9-9" />
    </svg>
  );
}

function IconButton({
  icon,
  label,
  onClick,
  disabled = false
}: {
  icon: IconName;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button className="icon-btn" onClick={onClick} type="button" disabled={disabled} aria-label={label} title={label}>
      <Icon name={icon} />
    </button>
  );
}

function ActionButton({
  icon,
  label,
  onClick,
  disabled = false,
  success = false
}: {
  icon: IconName;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  success?: boolean;
}) {
  return (
    <button
      className={`action-btn ${success ? "success" : ""}`}
      onClick={onClick}
      type="button"
      disabled={disabled}
      aria-label={label}
      title={label}
    >
      <Icon name={icon} />
      <span>{label}</span>
    </button>
  );
}

export default function MermaidCard({ diagram, title, compact = false }: Props) {
  const [inlineSvg, setInlineSvg] = useState<string>("");
  const [modalSvg, setModalSvg] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const diagramBaseId = useMemo(
    () => `m_${title.replace(/[^a-zA-Z0-9]/g, "_")}_${Math.random().toString(16).slice(2)}`,
    [title]
  );
  const inlineDiagramId = useMemo(() => `${diagramBaseId}_inline`, [diagramBaseId]);
  const modalDiagramId = useMemo(() => `${diagramBaseId}_modal`, [diagramBaseId]);
  const safeTitle = useMemo(() => title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, ""), [title]);
  const downloadableSvg = modalSvg || inlineSvg;
  const canDownload = downloadableSvg.includes("<svg");

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
        const graph = diagram || "flowchart LR\\nA-->B";
        const [inlineRendered, modalRendered] = await Promise.all([
          mermaid.render(inlineDiagramId, graph),
          mermaid.render(modalDiagramId, graph)
        ]);
        if (active) {
          setInlineSvg(inlineRendered.svg);
          setModalSvg(modalRendered.svg);
        }
      } catch (error) {
        if (active) {
          const message = error instanceof Error ? error.message : String(error);
          const errorSvg = `<pre>Mermaid render error: ${message}</pre>`;
          setInlineSvg(errorSvg);
          setModalSvg(errorSvg);
        }
      }
    }

    render();

    return () => {
      active = false;
    };
  }, [diagram, inlineDiagramId, modalDiagramId]);

  useEffect(() => {
    setModalOpen(false);
  }, [diagram, title]);

  useEffect(() => {
    if (!modalOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setModalOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [modalOpen]);

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
    const blob = new Blob([downloadableSvg], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${safeTitle || "diagram"}.svg`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function openModal() {
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
  }

  return (
    <div className="panel">
      <div className="diagram-header">
        <h2>{title}</h2>
      </div>
      <div
        className={`mermaid-shell mermaid-shell-interactive ${compact ? "compact" : ""}`}
        onClick={openModal}
        role="button"
        tabIndex={0}
        aria-label={`Open ${title} in modal`}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openModal();
          }
        }}
      >
        <div className="mermaid-static-content" dangerouslySetInnerHTML={{ __html: inlineSvg }} />
      </div>
      <p className="diagram-hint">Click to open full-screen modal.</p>
      <details className="diagram-raw">
        <summary>View Mermaid source</summary>
        <pre>{diagram}</pre>
      </details>
      {modalOpen ? (
        <div className="diagram-modal-overlay" onClick={closeModal}>
          <div
            className="diagram-modal"
            role="dialog"
            aria-modal="true"
            aria-label={`${title} interactive modal`}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="diagram-header">
              <h2>{title}</h2>
              <div className="diagram-toolbar">
                <div className="diagram-actions">
                  <ActionButton
                    icon={copied ? "check" : "copy"}
                    label={copied ? "Copied" : "Copy"}
                    onClick={copySource}
                    success={copied}
                  />
                  <ActionButton icon="download" label="SVG" onClick={downloadSvg} disabled={!canDownload} />
                  <IconButton icon="close" label="Close modal" onClick={closeModal} />
                </div>
              </div>
            </div>
            <div className="mermaid-shell mermaid-shell-modal">
              <div
                className="mermaid-static-content mermaid-modal-static"
                dangerouslySetInnerHTML={{ __html: modalSvg || inlineSvg }}
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
