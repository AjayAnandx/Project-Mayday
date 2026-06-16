import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'
import type { Components } from 'react-markdown'

interface MarkdownRendererProps {
  content: string
}

const components: Components = {
  code({ className, children, ...props }) {
    const isInline = !className
    if (isInline) {
      return (
        <code className="bg-surface1/70 text-green px-1 rounded text-[12px] font-mono" {...props}>
          {children}
        </code>
      )
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    )
  },
  pre({ children }) {
    return (
      <pre className="bg-black/60 border border-surface1/60 rounded-lg p-3 my-2 overflow-x-auto text-[12px] font-mono leading-relaxed">
        {children}
      </pre>
    )
  },
  h1({ children }) {
    return <h1 className="text-base font-bold text-green mb-1 mt-2">{children}</h1>
  },
  h2({ children }) {
    return <h2 className="text-sm font-bold text-green mb-1 mt-2">{children}</h2>
  },
  h3({ children }) {
    return <h3 className="text-sm font-semibold text-green mb-0.5 mt-1.5">{children}</h3>
  },
  h4({ children }) {
    return <h4 className="text-[13px] font-semibold text-green mb-0.5 mt-1.5">{children}</h4>
  },
  ul({ children }) {
    return <ul className="list-disc list-inside text-text space-y-0.5 my-1">{children}</ul>
  },
  ol({ children }) {
    return <ol className="list-decimal list-inside text-text space-y-0.5 my-1">{children}</ol>
  },
  li({ children }) {
    return <li className="text-[13px] leading-snug">{children}</li>
  },
  a({ href, children }) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-green underline hover:text-green/80 transition-colors"
      >
        {children}
      </a>
    )
  },
  blockquote({ children }) {
    return (
      <blockquote className="border-l-2 border-green/50 pl-3 my-2 italic text-overlay0 text-[13px]">
        {children}
      </blockquote>
    )
  },
  hr() {
    return <hr className="border-surface1/60 my-3" />
  },
  strong({ children }) {
    return <strong className="font-semibold text-text">{children}</strong>
  },
  em({ children }) {
    return <em className="italic text-text">{children}</em>
  },
  p({ children }) {
    return <p className="my-1 leading-snug text-[13px]">{children}</p>
  },
  table({ children }) {
    return (
      <div className="overflow-x-auto my-2">
        <table className="w-full border-collapse text-[12px]">{children}</table>
      </div>
    )
  },
  th({ children }) {
    return (
      <th className="border border-surface1/60 px-2 py-1 text-green font-semibold text-left bg-surface0/50">
        {children}
      </th>
    )
  },
  td({ children }) {
    return <td className="border border-surface1/60 px-2 py-1 text-text">{children}</td>
  },
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      rehypePlugins={[rehypeHighlight]}
      components={components}
    >
      {content}
    </ReactMarkdown>
  )
}
