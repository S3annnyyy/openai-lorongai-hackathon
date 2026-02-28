"use client";

import mermaid from "mermaid";
import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, WheelEvent as ReactWheelEvent } from "react";

type Props = {
  diagram: string;
  title: string;
  compact?: boolean;
};

type Viewport = {
  scale: number;
  x: number;
  y: number;
};

type DragState = {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startX: number;
  startY: number;
  moved: boolean;
};

type IconName = "plus" | "minus" | "reset" | "copy" | "download" | "close" | "check";

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const ZOOM_STEP = 0.2;
const ZOOM_WHEEL_SENSITIVITY = 0.002;
const CLICK_DRAG_THRESHOLD = 4;

function clampZoom(value: number): number {
  return Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Number(value.toFixed(2))));
}

function defaultViewport(): Viewport {
  return { scale: 1, x: 0, y: 0 };
}

function withScale(viewport: Viewport, nextScale: number, anchorX: number, anchorY: number): Viewport {
  if (nextScale === viewport.scale) return viewport;
  const canvasX = (anchorX - viewport.x) / viewport.scale;
  const canvasY = (anchorY - viewport.y) / viewport.scale;
  return {
    scale: nextScale,
    x: Number((anchorX - canvasX * nextScale).toFixed(2)),
    y: Number((anchorY - canvasY * nextScale).toFixed(2))
  };
}

function Icon({ name }: { name: IconName }) {
  if (name === "plus") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 5v14M5 12h14" />
      </svg>
    );
  }
  if (name === "minus") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 12h14" />
      </svg>
    );
  }
  if (name === "reset") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M20 12a8 8 0 1 1-2.35-5.65" />
        <path d="M20 4v6h-6" />
      </svg>
    );
  }
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
  const [svg, setSvg] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [modalViewport, setModalViewport] = useState<Viewport>(defaultViewport);
  const [dragging, setDragging] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const dragRef = useRef<DragState | null>(null);
  const modalShellRef = useRef<HTMLDivElement | null>(null);
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

  useEffect(() => {
    setModalViewport(defaultViewport());
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

  function updateViewport(updater: (current: Viewport) => Viewport) {
    setModalViewport((current) => updater(current));
  }

  function openModal() {
    setModalViewport(defaultViewport());
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
  }

  function resetViewport() {
    updateViewport(() => defaultViewport());
  }

  function zoomByStep(direction: -1 | 1) {
    const shell = modalShellRef.current;
    if (!shell) return;
    const rect = shell.getBoundingClientRect();
    const anchorX = rect.width / 2;
    const anchorY = rect.height / 2;
    updateViewport((current) => {
      const nextScale = clampZoom(current.scale + direction * ZOOM_STEP);
      return withScale(current, nextScale, anchorX, anchorY);
    });
  }

  function handleWheel(event: ReactWheelEvent<HTMLDivElement>) {
    event.preventDefault();
    const shell = modalShellRef.current;
    if (!shell) return;

    const rect = shell.getBoundingClientRect();
    const anchorX = event.clientX - rect.left;
    const anchorY = event.clientY - rect.top;

    if (event.ctrlKey || event.metaKey || event.altKey) {
      const factor = Math.exp(-event.deltaY * ZOOM_WHEEL_SENSITIVITY);
      updateViewport((current) => {
        const nextScale = clampZoom(current.scale * factor);
        return withScale(current, nextScale, anchorX, anchorY);
      });
      return;
    }

    updateViewport((current) => ({
      ...current,
      x: Math.round(current.x - event.deltaX),
      y: Math.round(current.y - event.deltaY)
    }));
  }

  function handlePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    const current = modalViewport;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: current.x,
      startY: current.y,
      moved: false
    };
    setDragging(true);
  }

  function handlePointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - drag.startClientX;
    const deltaY = event.clientY - drag.startClientY;
    if (Math.abs(deltaX) + Math.abs(deltaY) > CLICK_DRAG_THRESHOLD) {
      drag.moved = true;
    }
    updateViewport((current) => ({
      ...current,
      x: Math.round(drag.startX + deltaX),
      y: Math.round(drag.startY + deltaY)
    }));
  }

  function clearDrag(pointerId: number) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== pointerId) return;
    dragRef.current = null;
    setDragging(false);
  }

  function handlePointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    clearDrag(event.pointerId);
  }

  function handlePointerCancel(event: ReactPointerEvent<HTMLDivElement>) {
    clearDrag(event.pointerId);
  }

  const modalZoom = Math.round(modalViewport.scale * 100);

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
        <div className="mermaid-static-content" dangerouslySetInnerHTML={{ __html: svg }} />
      </div>
      <p className="diagram-hint">Click to open full-screen modal. Use drag, pinch, and wheel inside the modal.</p>
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
                <div className="zoom-group">
                  <IconButton
                    icon="minus"
                    label="Zoom out"
                    onClick={() => zoomByStep(-1)}
                    disabled={modalViewport.scale <= MIN_ZOOM}
                  />
                  <span className="zoom-level">{modalZoom}%</span>
                  <IconButton
                    icon="plus"
                    label="Zoom in"
                    onClick={() => zoomByStep(1)}
                    disabled={modalViewport.scale >= MAX_ZOOM}
                  />
                  <IconButton
                    icon="reset"
                    label="Reset view"
                    onClick={resetViewport}
                    disabled={modalViewport.scale === 1 && modalViewport.x === 0 && modalViewport.y === 0}
                  />
                </div>
                <div className="diagram-actions">
                  <ActionButton icon={copied ? "check" : "copy"} label={copied ? "Copied" : "Copy"} onClick={copySource} success={copied} />
                  <ActionButton icon="download" label="SVG" onClick={downloadSvg} disabled={!canDownload} />
                  <IconButton icon="close" label="Close modal" onClick={closeModal} />
                </div>
              </div>
            </div>
            <div
              ref={modalShellRef}
              className={`mermaid-shell mermaid-shell-modal ${dragging ? "dragging" : ""}`}
              onWheel={handleWheel}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerCancel}
              onDoubleClick={resetViewport}
            >
              <div className="mermaid-canvas">
                <div
                  className="mermaid-zoom-content"
                  style={{ transform: `translate(${modalViewport.x}px, ${modalViewport.y}px) scale(${modalViewport.scale})` }}
                  dangerouslySetInnerHTML={{ __html: svg }}
                />
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
