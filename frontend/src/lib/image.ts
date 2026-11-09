/** Shrink a picture in the browser before upload: the server sits behind a 1 MB nginx
 * limit, and phone photos are several MB. Re-encoded as JPEG (EXIF orientation applied
 * by the browser, EXIF itself dropped). */
export async function downscale(file: File, maxSide = 1600, quality = 0.85): Promise<Blob> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  try {
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const w = Math.max(1, Math.round(bitmap.width * scale));
    const h = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Rasmni qayta ishlab bo'lmadi");
    ctx.fillStyle = "#fff"; // transparent PNG/WEBP -> white, JPEG has no alpha
    ctx.fillRect(0, 0, w, h);
    ctx.drawImage(bitmap, 0, 0, w, h);
    const encode = (q: number) =>
      new Promise<Blob>((resolve, reject) =>
        canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Rasmni qayta ishlab bo'lmadi"))), "image/jpeg", q),
      );
    // the host nginx refuses bodies over 1 MB: lower the quality until it fits
    let blob = await encode(quality);
    for (const q of [0.7, 0.55]) {
      if (blob.size <= 950_000) break;
      blob = await encode(q);
    }
    return blob;
  } finally {
    bitmap.close();
  }
}
