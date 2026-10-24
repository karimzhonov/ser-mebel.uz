import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Download, ExternalLink, Loader2, Minus, Plus, X } from "lucide-react";
// Legacy build: runs in older iOS/Android WebViews (Telegram) too.
import * as pdfjs from "pdfjs-dist/legacy/build/pdf";
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.js?url";
import type { PDFDocumentProxy } from "pdfjs-dist/types/src/display/api";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

/** Full-screen PDF viewer drawn inside the panel (PDF.js), so a PDF opens the same
 * on a computer, a phone and inside Telegram — where the built-in viewers can't
 * show PDFs — and files saved without ".pdf" open too (it reads the bytes). */
export default function PdfViewer({
  url,
  name,
  downloadName,
  onClose,
}: {
  url: string;
  name: string;
  downloadName?: string | null;
  onClose: () => void;
}) {
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [width, setWidth] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    let loaded: PDFDocumentProxy | null = null;
    const task = pdfjs.getDocument({
      url,
      isEvalSupported: false,
      // Copied by scripts/copy-pdfjs-assets.mjs: fonts/encodings for non-embedded fonts.
      standardFontDataUrl: "/pdfjs/standard_fonts/",
      cMapUrl: "/pdfjs/cmaps/",
      cMapPacked: true,
    });
    task.promise.then(
      (d) => {
        loaded = d;
        if (!cancelled) setDoc(d);
      },
      () => !cancelled && setError("Faylni ochib bo'lmadi — u PDF emas yoki shikastlangan."),
    );
    return () => {
      cancelled = true;
      task.destroy();
      loaded?.destroy();
    };
  }, [url]);

  useEffect(() => {
    const measure = () => setWidth(Math.min((scroller.current?.clientWidth ?? 800) - 32, 1000));
    measure();
    window.addEventListener("resize", measure);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("keydown", esc);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const btn =
    "inline-flex h-9 w-9 items-center justify-center rounded-xl text-white/80 transition hover:bg-white/10 hover:text-white disabled:opacity-40";

  return createPortal(
    <div className="fixed inset-0 z-[70] flex flex-col bg-slate-900/95 animate-fade-in">
      <header className="flex items-center gap-2 border-b border-white/10 px-3 py-2 pt-[max(8px,env(safe-area-inset-top))] text-white">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{name}</div>
          {doc && <div className="text-xs text-white/60">{doc.numPages} sahifa</div>}
        </div>
        <button className={btn} title="Kichraytirish" disabled={zoom <= 0.5} onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}>
          <Minus className="h-4 w-4" />
        </button>
        <span className="w-12 text-center text-xs tabular-nums text-white/70">{Math.round(zoom * 100)}%</span>
        <button className={btn} title="Kattalashtirish" disabled={zoom >= 3} onClick={() => setZoom((z) => Math.min(3, z + 0.25))}>
          <Plus className="h-4 w-4" />
        </button>
        <a className={btn} href={url} download={downloadName || name} title="Yuklab olish">
          <Download className="h-4 w-4" />
        </a>
        <a className={btn} href={url} target="_blank" rel="noreferrer" title="Yangi oynada ochish">
          <ExternalLink className="h-4 w-4" />
        </a>
        <button className={btn} title="Yopish" onClick={onClose}>
          <X className="h-5 w-5" />
        </button>
      </header>
      <div ref={scroller} className="flex-1 overflow-auto px-4 py-4">
        {error && <p className="mx-auto mt-20 max-w-sm text-center text-sm text-rose-200">{error}</p>}
        {!doc && !error && (
          <div className="mt-24 flex justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-white/70" />
          </div>
        )}
        {doc && width > 0 && (
          <div className="mx-auto flex flex-col items-center gap-4">
            {Array.from({ length: doc.numPages }, (_, i) => (
              <PdfPage key={i} doc={doc} number={i + 1} width={width * zoom} root={scroller.current} />
            ))}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
}

/** One page, rendered only when it scrolls near the screen (big PDFs stay fast). */
function PdfPage({
  doc,
  number,
  width,
  root,
}: {
  doc: PDFDocumentProxy;
  number: number;
  width: number;
  root: HTMLElement | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = useState(number <= 2);
  const [ratio, setRatio] = useState(1.414); // A4 until the real size is known

  useEffect(() => {
    if (visible || !box.current) return;
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && setVisible(true), {
      root,
      rootMargin: "800px 0px",
    });
    io.observe(box.current);
    return () => io.disconnect();
  }, [visible, root]);

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    let renderTask: { cancel: () => void } | null = null;
    doc.getPage(number).then((page) => {
      if (cancelled || !canvas.current) return;
      const base = page.getViewport({ scale: 1 });
      setRatio(base.height / base.width);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const viewport = page.getViewport({ scale: (width / base.width) * dpr });
      const c = canvas.current;
      c.width = Math.floor(viewport.width);
      c.height = Math.floor(viewport.height);
      const task = page.render({ canvasContext: c.getContext("2d")!, viewport });
      renderTask = task;
      task.promise.catch(() => {});
    });
    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [visible, doc, number, width]);

  return (
    <div ref={box} className="relative bg-white shadow-pop" style={{ width, height: width * ratio }}>
      {visible && <canvas ref={canvas} className="h-full w-full" />}
      <span className="absolute bottom-1 right-2 rounded bg-black/40 px-1.5 text-[10px] text-white">{number}</span>
    </div>
  );
}
