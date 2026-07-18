'use client'

import { useState, useCallback } from 'react'
import clsx from 'clsx'

type UploadState = 'idle' | 'dragging' | 'uploading' | 'done' | 'error'

interface UploadedFile {
  name: string
  size: number
  status: 'pending' | 'uploading' | 'done' | 'error'
  errorMsg?: string
}

interface RAGUploaderProps {
  tenantId: string
  onUploadComplete?: (count: number) => void
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000'

export default function RAGUploader({ tenantId, onUploadComplete }: RAGUploaderProps) {
  const [uploadState, setUploadState] = useState<UploadState>('idle')
  const [files, setFiles] = useState<UploadedFile[]>([])

  const addFiles = (incoming: FileList | null) => {
    if (!incoming) return
    const accepted = Array.from(incoming).filter(f =>
      f.name.endsWith('.md') || f.name.endsWith('.txt') || f.name.endsWith('.pdf'),
    )
    setFiles(prev => [
      ...prev,
      ...accepted.map(f => ({ name: f.name, size: f.size, status: 'pending' as const })),
    ])
  }

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setUploadState('dragging')
  }, [])

  const onDragLeave = useCallback(() => {
    setUploadState('idle')
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setUploadState('idle')
    addFiles(e.dataTransfer.files)
  }, [])

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    addFiles(e.target.files)
    e.target.value = ''
  }

  const upload = async () => {
    if (files.length === 0) return
    setUploadState('uploading')

    let successCount = 0
    const updated = [...files]

    for (let i = 0; i < updated.length; i++) {
      if (updated[i].status === 'done') continue
      updated[i] = { ...updated[i], status: 'uploading' }
      setFiles([...updated])

      try {
        const form = new FormData()
        form.append('file', new File([], updated[i].name))
        form.append('tenant_id', tenantId)

        const res = await fetch(`${API_BASE}/api/rag/upload`, {
          method: 'POST',
          body: form,
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        updated[i] = { ...updated[i], status: 'done' }
        successCount++
      } catch (err) {
        updated[i] = {
          ...updated[i],
          status: 'error',
          errorMsg: err instanceof Error ? err.message : 'Upload failed',
        }
      }
      setFiles([...updated])
    }

    setUploadState(updated.some(f => f.status === 'error') ? 'error' : 'done')
    onUploadComplete?.(successCount)
  }

  const removeFile = (idx: number) => {
    setFiles(prev => prev.filter((_, i) => i !== idx))
  }

  const reset = () => {
    setFiles([])
    setUploadState('idle')
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Drop zone */}
      <div
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={clsx(
          'relative flex flex-col items-center justify-center gap-2 rounded-lg p-10 transition-colors cursor-pointer',
          uploadState === 'dragging'
            ? 'bg-bizon-blue/5 border-bizon-blue'
            : 'bg-surface hover:border-bizon-blue/40',
        )}
        style={{ border: `0.5px dashed ${uploadState === 'dragging' ? '#0295fd' : 'var(--border)'}` }}
        onClick={() => document.getElementById('rag-file-input')?.click()}
      >
        <input
          id="rag-file-input"
          type="file"
          multiple
          accept=".md,.txt,.pdf"
          className="sr-only"
          onChange={handleFileInput}
        />
        <span className="text-3xl select-none">📄</span>
        <div className="text-center">
          <p className="text-sm font-medium">
            {uploadState === 'dragging' ? 'Drop files here' : 'Drag & drop or click to select'}
          </p>
          <p className="text-xs text-muted mt-0.5">Supports .md, .txt, .pdf</p>
        </div>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {files.map((f, i) => (
            <div
              key={i}
              className="flex items-center gap-2 px-3 py-2 rounded-md bg-surface text-xs font-mono"
              style={{ border: '0.5px solid var(--border)' }}
            >
              <span
                className={clsx(
                  'w-1.5 h-1.5 rounded-full flex-shrink-0',
                  f.status === 'done'      ? 'bg-bizon-success'
                    : f.status === 'error'   ? 'bg-bizon-danger'
                    : f.status === 'uploading' ? 'bg-bizon-blue'
                    : 'bg-neutral-500',
                )}
              />
              <span className="flex-1 truncate">{f.name}</span>
              <span className="text-muted text-2xs">{(f.size / 1024).toFixed(1)} KB</span>
              {f.errorMsg && <span className="text-bizon-danger text-2xs">{f.errorMsg}</span>}
              {f.status === 'pending' && (
                <button
                  onClick={() => removeFile(i)}
                  className="text-muted hover:text-bizon-danger transition-colors ml-1"
                  aria-label="Remove"
                >
                  ×
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        {files.some(f => f.status === 'pending' || f.status === 'error') && (
          <button
            onClick={upload}
            disabled={uploadState === 'uploading'}
            className="px-4 py-2 text-sm font-medium rounded-md bg-bizon-blue text-white disabled:opacity-50 transition-opacity"
          >
            {uploadState === 'uploading' ? 'Uploading…' : 'Upload to RAG'}
          </button>
        )}
        {files.length > 0 && uploadState !== 'uploading' && (
          <button
            onClick={reset}
            className="px-4 py-2 text-sm font-medium rounded-md text-muted hover:text-white transition-colors"
            style={{ border: '0.5px solid var(--border)' }}
          >
            Clear
          </button>
        )}
      </div>

      {uploadState === 'done' && !files.some(f => f.status === 'error') && (
        <p className="text-xs text-bizon-success font-mono">
          All files indexed into RAG for {tenantId}.
        </p>
      )}
    </div>
  )
}
