export function pdfPageUrl(documentId: string, page: number, sourceHash?: string) {
  const source = sourceHash ? "&source=" + encodeURIComponent(sourceHash) : ""
  return `/api/documents/view/${encodeURIComponent(documentId)}?page=${page}${source}#page=${page}`
}
