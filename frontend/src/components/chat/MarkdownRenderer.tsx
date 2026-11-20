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
        <code className="bg-white/[0.07] text-green px-1.5 py-0.5 rounded-md text-[0.85em] font-mono" {...props}>
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
      <pre className="bg-black/60 border border-white/[0.07] rounded-xl p-3.5 my-3 overflow-x-auto text-[12px] font-mono leading-relaxed">
        {children}
      </pre>
    )
  },
  h1({ children }) {
    return <h1 className="text-lg font-semibold text-text mb-2 mt-4 first:mt-0">{children}</h1>
  },
  h2({ children }) {
    return <h2 className="text-base font-semibold text-text mb-1.5 mt-4 first:mt-0">{children}</h2>
  },
  h3({ children }) {
    return <h3 className="font-semibold text-green mb-1 mt-3 first:mt-0">{children}</h3>
  },
  h4({ children }) {
    return <h4 className="font-semibold text-subtext1 mb-1 mt-3 first:mt-0">{children}</h4>
  },
  ul({ children }) {
    return <ul className="list-disc pl-5 marker:text-green/70 text-text space-y-1 my-2">{children}</ul>
  },
  ol({ children }) {
    return <ol className="list-decimal pl-5 marker:text-overlay1 text-text space-y-1 my-2">{children}</ol>
  },
  li({ children }) {
    return <li className="leading-relaxed pl-0.5">{children}</li>
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
      <blockquote className="border-l-2 border-green/50 pl-3 my-3 text-subtext0">
        {children}
      </blockquote>
    )
  },
  hr() {
    return <hr className="border-white/[0.07] my-4" />
  },
  strong({ children }) {
    return <strong className="font-semibold text-text">{children}</strong>
  },
  em({ children }) {
    return <em className="italic text-text">{children}</em>
  },
  p({ children }) {
    return <p className="my-2 first:mt-0 last:mb-0 leading-relaxed">{children}</p>
  },
  table({ children }) {
    return (
      <div className="overflow-x-auto my-3 rounded-xl border border-white/[0.07]">
        <table className="w-full border-collapse text-[12px]">{children}</table>
      </div>
    )
  },
  th({ children }) {
    return (
      <th className="border-b border-white/[0.07] px-3 py-2 text-subtext1 font-semibold text-left bg-white/[0.03]">
        {children}
      </th>
    )
  },
  td({ children }) {
    return <td className="border-b border-white/[0.05] px-3 py-2 text-text">{children}</td>
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
