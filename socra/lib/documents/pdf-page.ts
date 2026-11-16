export function pdfPageUrl(documentId: string, page: number) {
  return `/api/documents/view/${encodeURIComponent(documentId)}?page=${page}#page=${page}`
}
