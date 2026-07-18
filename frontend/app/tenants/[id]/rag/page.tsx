import Link from 'next/link'
import RAGUploader from '@/components/RAGUploader'

interface Props {
  params: { id: string }
}

const MOCK_INDEXED = [
  { name: 'servicios.md',     chunks: 12, updated: '2026-07-10' },
  { name: 'precios.md',       chunks: 8,  updated: '2026-07-10' },
  { name: 'tiempos.md',       chunks: 5,  updated: '2026-07-11' },
  { name: 'target_market.md', chunks: 9,  updated: '2026-07-12' },
]

export default function RAGPage({ params }: Props) {
  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <div className="flex items-center gap-2 text-sm text-muted font-mono mb-1">
          <Link href={`/tenants/${params.id}`} className="hover:text-white transition-colors">
            {params.id}
          </Link>
          <span>/</span>
          <span>rag</span>
        </div>
        <h1 className="text-lg font-bold tracking-tight">Knowledge Base</h1>
        <p className="text-xs text-muted font-mono mt-0.5">
          Collection: <span style={{ color: '#0295fd' }}>rag_{params.id}</span>
        </p>
      </div>

      {/* Upload zone */}
      <section>
        <h2 className="text-sm font-medium mb-3">Upload documents</h2>
        <RAGUploader tenantId={params.id} />
      </section>

      {/* Indexed docs */}
      <section>
        <h2 className="text-sm font-medium mb-3">Indexed documents</h2>
        <div className="rounded-lg overflow-hidden" style={{ border: '0.5px solid var(--border)' }}>
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="bg-surface" style={{ borderBottom: '0.5px solid var(--border)' }}>
                {['Document', 'Chunks', 'Last indexed'].map(h => (
                  <th key={h} className="text-left px-3 py-2 text-muted font-medium uppercase tracking-widest text-2xs">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {MOCK_INDEXED.map((doc, i) => (
                <tr
                  key={doc.name}
                  className="hover:bg-surface/60 transition-colors"
                  style={{ borderBottom: i < MOCK_INDEXED.length - 1 ? '0.5px solid var(--border)' : undefined }}
                >
                  <td className="px-3 py-2.5">{doc.name}</td>
                  <td className="px-3 py-2.5 text-muted">{doc.chunks}</td>
                  <td className="px-3 py-2.5 text-muted">{doc.updated}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-2xs text-muted font-mono mt-2">
          {MOCK_INDEXED.reduce((s, d) => s + d.chunks, 0)} total chunks indexed
        </p>
      </section>
    </div>
  )
}
