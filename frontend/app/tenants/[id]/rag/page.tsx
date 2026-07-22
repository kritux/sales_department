import Link from 'next/link'
import RAGManager from '@/components/RAGManager'

interface Props {
  params: { id: string }
}

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

      <RAGManager tenantId={params.id} />
    </div>
  )
}
