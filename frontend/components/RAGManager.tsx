'use client'

import { useState, useCallback, useEffect } from 'react'
import clsx from 'clsx'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'
const RAG_API = `${API_BASE}/api/v1/rag`

interface RAGDoc {
  filename: string
  size_bytes: number
  last_modified: string   // ISO 8601 UTC
}

export interface RAGManagerProps {
  tenantId: string
  authToken?: string
}

type UploadState = 'idle' | 'dragging' | 'uploading' | 'done' | 'error'

interface QueuedFile {
  file: File
  status: 'pending' | 'uploading' | 'done' | 'error'
  errorMsg?: string
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      month: 'short', day: 'numeric', year: 'numeric',
    })
  } catch {
    return iso
  }
}

export default function RAGManager({
  tenantId,
  authToken = process.env.NEXT_PUBLIC_API_TOKEN ?? '',
}: RAGManagerProps) {
  const [docs, setDocs] = useState<RAGDoc[]>([])
  const [docsLoading, setDocsLoading] = useState(true)
  const [docsError, setDocsError] = useState('')
  const [queue, setQueue] = useState<QueuedFile[]>([])
  const [uploadState, setUploadState] = useState<UploadState>('idle')
  const [deletingFile, setDeletingFile] = useState<string | null>(null)

  const authHeaders = authToken ? { Authorization: `Bearer ${authToken}` } : {}

  const fetchDocs = useCallback(async () => {
    setDocsLoading(true)
    setDocsError('')
    try {
      const resp = await fetch(`${RAG_API}/${tenantId}/documents`, {
        headers: authHeaders,
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = await resp.json()
      setDocs(data.documents ?? [])
    } catch (err) {
      setDocsError(err instanceof Error ? err.message : 'Could not load documents')
    } finally {
      setDocsLoading(false)
    }
  }, [tenantId, authToken])

  useEffect(() => { fetchDocs() }, [fetchDocs])

  const addFiles = (incoming: FileList | null) => {
    if (!incoming) return
    const accepted = Array.from(incoming).filter(
      f => f.name.endsWith('.md') || f.name.endsWith('.txt') || f.name.endsWith('.pdf'),
    )
    setQueue(prev => [
      ...prev,
      ...accepted.map(f => ({ file: f, status: 'pending' as const })),
    ])
  }

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setUploadState('dragging')
  }, [])

  const onDragLeave = useCallback(() => setUploadState('idle'), [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setUploadState('idle')
    addFiles(e.dataTransfer.files)
  }, [])

  const uploadAll = async () => {
    if (queue.length === 0) return
    setUploadState('uploading')
    const updated = [...queue]

    for (let i = 0; i < updated.length; i++) {
      if (updated[i].status === 'done') continue
      updated[i] = { ...updated[i], status: 'uploading' }
      setQueue([...updated])

      const form = new FormData()
      form.append('file', updated[i].file)
      try {
        const resp = await fetch(`${RAG_API}/${tenantId}/upload`, {
          method: 'POST',
          headers: authHeaders,
          body: form,
        })
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        updated[i] = { ...updated[i], status: 'done' }
      } catch (err) {
        updated[i] = {
          ...updated[i],
          status: 'error',
          errorMsg: err instanceof Error ? err.message : 'Upload failed',
        }
      }
      setQueue([...updated])
    }

    setUploadState(updated.some(f => f.status === 'error') ? 'error' : 'done')
    await fetchDocs()
  }

  const deleteDoc = async (filename: string) => {
    if (deletingFile) return
    setDeletingFile(filename)
    try {
      const resp = await fetch(
        `${RAG_API}/${tenantId}/documents/${encodeURIComponent(filename)}`,
        { method: 'DELETE', headers: authHeaders },
      )
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      await fetchDocs()
    } catch (err) {
      console.error('Delete failed:', err)
    } finally {
      setDeletingFile(null)
    }
  }

  const clearQueue = () => { setQueue([]); setUploadState('idle') }
  const removeFromQueue = (idx: number) =>
    setQueue(prev => prev.filter((_, i) => i !== idx))

  return (
    <div className="flex flex-col gap-6" data-testid="rag-manager">
      {/* ── Drop zone ───────────────────────────────────────── */}
      <div
        data-testid="drop-zone"
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        onClick={() => document.getElementById('ragmanager-input')?.click()}
        className={clsx(
          'relative flex flex-col items-center justify-center gap-2 rounded-lg p-10',
          'transition-colors cursor-pointer',
          uploadState === 'dragging'
            ? 'bg-bizon-blue/5'
            : 'bg-surface hover:border-bizon-blue/40',
        )}
        style={{
          border: `0.5px dashed ${
            uploadState === 'dragging' ? '#0295fd' : 'var(--border)'
          }`,
        }}
      >
        <input
          id="ragmanager-input"
          type="file"
          multiple
          accept=".md,.txt,.pdf"
          className="sr-only"
          onChange={e => { addFiles(e.target.files); e.target.value = '' }}
        />
        <span className="text-3xl select-none">📄</span>
        <div className="text-center">
          <p className="text-sm font-medium">
            {uploadState === 'dragging' ? 'Drop files here' : 'Drag & drop or click to upload'}
          </p>
          <p className="text-xs text-muted mt-0.5">
            Supports .md, .txt, .pdf — auto-indexed to RAG after upload
          </p>
        </div>
      </div>

      {/* ── Upload queue ────────────────────────────────────── */}
      {queue.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {queue.map((item, i) => (
            <div
              key={i}
              className="flex items-center gap-2 px-3 py-2 rounded-md bg-surface text-xs font-mono"
              style={{ border: '0.5px solid var(--border)' }}
            >
              <span
                className={clsx(
                  'w-1.5 h-1.5 rounded-full flex-shrink-0',
                  item.status === 'done'       ? 'bg-bizon-success'
                    : item.status === 'error'   ? 'bg-bizon-danger'
                    : item.status === 'uploading' ? 'bg-bizon-blue animate-pulse'
                    : 'bg-neutral-500',
                )}
              />
              <span className="flex-1 truncate">{item.file.name}</span>
              <span className="text-muted text-2xs">{formatSize(item.file.size)}</span>
              {item.errorMsg && (
                <span className="text-bizon-danger text-2xs">{item.errorMsg}</span>
              )}
              {item.status === 'pending' && (
                <button
                  onClick={() => removeFromQueue(i)}
                  className="text-muted hover:text-bizon-danger transition-colors ml-1"
                  aria-label={`Remove ${item.file.name}`}
                >
                  ×
                </button>
              )}
            </div>
          ))}

          <div className="flex gap-2 mt-1">
            {queue.some(f => f.status === 'pending' || f.status === 'error') && (
              <button
                onClick={uploadAll}
                disabled={uploadState === 'uploading'}
                className="px-4 py-2 text-sm font-medium rounded-md bg-bizon-blue text-white disabled:opacity-50 transition-opacity"
              >
                {uploadState === 'uploading' ? 'Uploading…' : 'Upload to RAG'}
              </button>
            )}
            {uploadState !== 'uploading' && (
              <button
                onClick={clearQueue}
                className="px-4 py-2 text-sm font-medium rounded-md text-muted hover:text-white transition-colors"
                style={{ border: '0.5px solid var(--border)' }}
              >
                Clear
              </button>
            )}
          </div>
        </div>
      )}

      {/* ── Indexed documents ────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium" data-testid="docs-heading">
            Indexed documents
          </h2>
          <span className="text-xs text-muted font-mono">
            {docsLoading
              ? '…'
              : `${docs.length} file${docs.length !== 1 ? 's' : ''}`}
          </span>
        </div>

        {docsError && (
          <p className="text-xs text-bizon-danger font-mono mb-2" data-testid="docs-error">
            {docsError}
          </p>
        )}

        {!docsLoading && docs.length === 0 && !docsError && (
          <p className="text-xs text-muted font-mono" data-testid="docs-empty">
            No documents indexed yet. Upload a .md, .txt, or .pdf above.
          </p>
        )}

        {docs.length > 0 && (
          <div
            className="rounded-lg overflow-hidden"
            style={{ border: '0.5px solid var(--border)' }}
            data-testid="docs-table"
          >
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="bg-surface" style={{ borderBottom: '0.5px solid var(--border)' }}>
                  {['Document', 'Size', 'Last indexed', ''].map((h, idx) => (
                    <th
                      key={idx}
                      className="text-left px-3 py-2 text-muted font-medium uppercase tracking-widest text-2xs"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {docs.map((doc, i) => (
                  <tr
                    key={doc.filename}
                    className="hover:bg-surface/60 transition-colors group"
                    style={{
                      borderBottom:
                        i < docs.length - 1 ? '0.5px solid var(--border)' : undefined,
                    }}
                  >
                    <td className="px-3 py-2.5">{doc.filename}</td>
                    <td className="px-3 py-2.5 text-muted">{formatSize(doc.size_bytes)}</td>
                    <td className="px-3 py-2.5 text-muted">{formatDate(doc.last_modified)}</td>
                    <td className="px-3 py-2.5 text-right">
                      <button
                        onClick={() => deleteDoc(doc.filename)}
                        disabled={deletingFile === doc.filename}
                        className="text-muted hover:text-bizon-danger transition-colors opacity-0 group-hover:opacity-100 disabled:opacity-50 text-xs"
                        aria-label={`Delete ${doc.filename}`}
                        data-testid={`delete-${doc.filename}`}
                      >
                        {deletingFile === doc.filename ? '…' : 'Delete'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
