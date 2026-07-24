const SUPPORTED_RESUME_EXTENSIONS = new Set([
  ".pdf",
  ".doc",
  ".docx",
  ".png",
  ".jpg",
  ".jpeg",
  ".xls",
  ".xlsx",
  ".html",
  ".htm",
]);

export function resumeFileExtension(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}

export function isSupportedResumeFile(file: File): boolean {
  return SUPPORTED_RESUME_EXTENSIONS.has(resumeFileExtension(file.name));
}

export function resumeFileTypeLabel(filename: string): string {
  const extension = resumeFileExtension(filename);
  if (extension === ".pdf") return "PDF";
  if (extension === ".doc" || extension === ".docx") return "Word";
  if (extension === ".xls" || extension === ".xlsx") return "Excel";
  if (extension === ".png" || extension === ".jpg" || extension === ".jpeg") return "图片";
  if (extension === ".html" || extension === ".htm") return "HTML";
  return "文件";
}

export function canPreviewInline(filename: string): boolean {
  const extension = resumeFileExtension(filename);
  // HTML is accepted as an extraction source, never as browser-previewable
  // content. The API also forces it to an opaque attachment; keeping it out
  // of this branch prevents a future response-policy regression from turning
  // a candidate-controlled document into a same-origin preview.
  return [".pdf", ".png", ".jpg", ".jpeg"].includes(extension);
}
