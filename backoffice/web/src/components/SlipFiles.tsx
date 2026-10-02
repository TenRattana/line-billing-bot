import { KeyboardEvent, MouseEvent, useEffect, useRef, useState } from "react";

import { api } from "../api";

type SlipFile = {
  index: number;
  name: string;
  mime_type: string;
  file_size: number | null;
  available: boolean;
  url: string;
};

const size = (bytes: number | null) =>
  bytes == null
    ? ""
    : bytes < 1024
      ? `${bytes} B`
      : bytes < 1024 * 1024
        ? `${(bytes / 1024).toFixed(0)} KB`
        : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

/** Full-size viewer on the page (native <dialog>): ‹ › or arrow keys, Esc / backdrop closes. */
function Viewer({ images, at, onMove, onClose }: { images: SlipFile[]; at: number; onMove: (i: number) => void; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const image = images[at];
  const step = (by: number) => onMove((at + by + images.length) % images.length);

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowRight") step(1);
    if (e.key === "ArrowLeft") step(-1);
  };

  // A click on the backdrop lands on the <dialog> itself, not on its content.
  const onBackdrop = (e: MouseEvent) => e.target === dialog.current && dialog.current?.close();

  return (
    <dialog ref={dialog} className="viewer" onClose={onClose} onKeyDown={onKey} onClick={onBackdrop} aria-label="ดูสลิป">
      <div className="viewer-head">
        <span className="mono">{image.name}</span>
        {images.length > 1 && (
          <span className="muted num">
            {at + 1} / {images.length}
          </span>
        )}
        <span className="spacer" />
        <a href={image.url} download>
          ดาวน์โหลด
        </a>
        <button className="ghost" onClick={() => dialog.current?.close()} aria-label="ปิด">
          ✕
        </button>
      </div>
      <div className="viewer-body">
        {images.length > 1 && (
          <button className="viewer-nav" onClick={() => step(-1)} aria-label="รูปก่อนหน้า">
            ‹
          </button>
        )}
        <img src={image.url} alt={`สลิป ${image.name}`} />
        {images.length > 1 && (
          <button className="viewer-nav" onClick={() => step(1)} aria-label="รูปถัดไป">
            ›
          </button>
        )}
      </div>
    </dialog>
  );
}

/** The slips attached to a sent bill: images open in a viewer, other files as links. */
export default function SlipFiles({ sendId }: { sendId: string }) {
  const [files, setFiles] = useState<SlipFile[] | null>(null);
  const [error, setError] = useState("");
  const [viewing, setViewing] = useState<number | null>(null);

  useEffect(() => {
    let current = true;
    setFiles(null);
    setError("");
    setViewing(null);
    api<SlipFile[]>(`/bill_sends/${encodeURIComponent(sendId)}/files`)
      .then((result) => current && setFiles(result))
      .catch((e) => current && setError(e.message));
    return () => {
      current = false;
    };
  }, [sendId]);

  const images = (files ?? []).filter((f) => f.available && f.mime_type.startsWith("image/"));

  return (
    <div className="card">
      <div className="chart-title">สลิปที่แนบ</div>
      {error && <div className="error">{error}</div>}
      {!files && !error && <div className="muted">กำลังโหลด…</div>}
      {files?.length === 0 && <div className="muted">ไม่มีข้อมูลไฟล์ของการส่งครั้งนี้</div>}
      <div className="slips">
        {files?.map((file) =>
          !file.available ? (
            <div key={file.index} className="slip missing">
              <span>ไม่พบไฟล์บน server</span>
              <span className="mono muted">{file.name}</span>
            </div>
          ) : file.mime_type.startsWith("image/") ? (
            <button
              key={file.index}
              className="slip"
              onClick={() => setViewing(images.indexOf(file))}
              title="ดูขนาดเต็ม"
            >
              <img src={file.url} alt={`สลิป ${file.name}`} loading="lazy" />
              <span className="mono muted">{file.name}</span>
            </button>
          ) : (
            <a key={file.index} className="slip file" href={file.url} target="_blank" rel="noreferrer">
              <span>📄 {file.name}</span>
              <span className="muted">{size(file.file_size)}</span>
            </a>
          ),
        )}
      </div>
      {viewing !== null && images[viewing] && (
        <Viewer images={images} at={viewing} onMove={setViewing} onClose={() => setViewing(null)} />
      )}
    </div>
  );
}
