export interface DocumentMeta {
  id: string
  filename: string
  pages: number
  title: string
  author: string
  size: number
  sha256: string
  needs_ocr: boolean
  uploaded_at: string
  status?: string
  summary?: string
}
