// PDF.js needs its standard fonts and CMaps at runtime to draw PDFs whose fonts
// aren't embedded (common for Word/Excel exports, Cyrillic text). Copied into
// public/ before dev/build so they're served from /pdfjs/… (public/pdfjs is ignored by git).
import { cpSync, mkdirSync } from "node:fs";

const src = "node_modules/pdfjs-dist";
const dst = "public/pdfjs";
mkdirSync(dst, { recursive: true });
for (const dir of ["standard_fonts", "cmaps"]) {
  cpSync(`${src}/${dir}`, `${dst}/${dir}`, { recursive: true });
}
console.log("pdfjs assets copied to", dst);
