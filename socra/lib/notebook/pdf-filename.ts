export function notebookPdfFilename(title: string) {
  const clean = title.trim().replace(/\.pdf$/i, "").replace(/[<>:"/\\|?*\u0000-\u001f]/g, "-")
  const stem = Array.from(clean).slice(0, 150).join("").replace(/[. ]+$/g, "") || "Notebook"
  const reserved = /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(stem)
  return `${reserved ? "_" : ""}${stem}.pdf`
}
