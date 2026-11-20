/**
 * Mayday's OpenUI component library.
 *
 * The backend (backend/core/openui_builder.py) writes OpenUI Lang that targets exactly these
 * components. Arguments are POSITIONAL in the order of each Zod object below, so changing a
 * field order is a breaking change: update the builder and run the contract test
 * (`python -m pytest backend/test_openui_builder.py`). OpenUI requires Zod 4 schemas, hence `zod/v4`.
 */
import { createLibrary, defineComponent, useTriggerAction, action } from '@openuidev/react-lang'
import { z } from 'zod/v4'
import { Download as DownloadIcon, ExternalLink } from 'lucide-react'
import { cn } from '../lib/utils'
import { MarkdownRenderer } from '../components/chat/MarkdownRenderer'
import { ChartView } from './ChartView'

const TIER = z.enum(['primary', 'secondary', 'tertiary', 'unknown'])

export const Text = defineComponent({
  name: 'Text',
  description: 'A block of markdown text.',
  props: z.object({ content: z.string() }),
  component: ({ props }) => <div className="text-sm"><MarkdownRenderer content={props.content} /></div>,
})

export const Metric = defineComponent({
  name: 'Metric',
  description: 'One key number with a label and optional hint.',
  props: z.object({ label: z.string(), value: z.string(), hint: z.string().optional() }),
  component: ({ props }) => (
    <div className="rounded-2xl bg-white/[0.03] border border-white/[0.06] px-4 py-3 min-w-[120px] flex-1">
      <p className="text-[11px] text-subtext0 truncate">{props.label}</p>
      <p className="mt-1 text-2xl font-medium tracking-tight text-text tabular-nums">{props.value}</p>
      {props.hint && <p className="mt-0.5 text-[11px] text-overlay1">{props.hint}</p>}
    </div>
  ),
})

export const MetricRow = defineComponent({
  name: 'MetricRow',
  description: 'A row of Metric cards.',
  props: z.object({ items: z.array(Metric.ref) }),
  component: ({ props, renderNode }) => <div className="flex flex-wrap gap-2">{renderNode(props.items)}</div>,
})

const Series = z.object({ name: z.string(), values: z.array(z.number()) })

export const Chart = defineComponent({
  name: 'Chart',
  description: 'A bar, line or pie chart. Each series has one value per label.',
  props: z.object({
    kind: z.enum(['bar', 'line', 'pie']),
    title: z.string(),
    labels: z.array(z.string()),
    series: z.array(Series),
    unit: z.string().optional(),
  }),
  component: ({ props }) => <ChartView {...props} />,
})

export const Table = defineComponent({
  name: 'Table',
  description: 'A data table: column headers and rows of cell strings.',
  props: z.object({ columns: z.array(z.string()), rows: z.array(z.array(z.string())), caption: z.string().optional() }),
  component: ({ props }) => (
    <div className="overflow-x-auto rounded-2xl border border-white/[0.06]">
      <table className="w-full text-xs">
        {props.caption && <caption className="px-3 pt-2 text-left text-[11px] text-overlay1">{props.caption}</caption>}
        <thead><tr>{props.columns.map((c, i) => <th key={i} className="px-3 py-2 text-left font-medium text-subtext0 whitespace-nowrap">{c}</th>)}</tr></thead>
        <tbody className="divide-y divide-white/[0.05]">
          {props.rows.map((r, i) => (
            <tr key={i}>{r.map((cell, j) => <td key={j} className="px-3 py-1.5 text-subtext1 align-top">{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  ),
})

const SourceItem = z.object({ n: z.number(), title: z.string(), url: z.string(), tier: TIER })

const TIER_STYLE: Record<string, string> = {
  primary: 'bg-green/15 text-green', secondary: 'bg-yellow/15 text-yellow',
  tertiary: 'bg-white/[0.06] text-subtext0', unknown: 'bg-white/[0.04] text-overlay1',
}

export function safeUrl(url: string): string | undefined {
  return /^https?:\/\//i.test(url) || url.startsWith('/') ? url : undefined
}

export const SourceList = defineComponent({
  name: 'SourceList',
  description: 'Numbered list of cited sources with their tier.',
  props: z.object({ items: z.array(SourceItem) }),
  component: ({ props }) => (
    <ol className="space-y-1">
      {props.items.map(s => (
        <li key={s.n} className="flex items-baseline gap-2 text-xs">
          <span className="w-6 shrink-0 text-right text-overlay1 tabular-nums">[{s.n}]</span>
          <a href={safeUrl(s.url)} target="_blank" rel="noreferrer" className="truncate text-subtext1 hover:text-green">{s.title || s.url}</a>
          <span className={cn('rounded-md px-1.5 py-0.5 text-[10px]', TIER_STYLE[s.tier])}>{s.tier}</span>
        </li>
      ))}
    </ol>
  ),
})

export const Download = defineComponent({
  name: 'Download',
  description: 'A downloadable file (report, spreadsheet, dataset).',
  props: z.object({ title: z.string(), url: z.string(), format: z.string() }),
  component: ({ props }) => (
    <a href={safeUrl(props.url)} target="_blank" rel="noreferrer"
       className="flex items-center gap-3 rounded-2xl border border-white/[0.06] px-4 py-3 hover:bg-white/[0.04]">
      <DownloadIcon className="h-4 w-4 text-green shrink-0" />
      <span className="flex-1 truncate text-sm text-text">{props.title}</span>
      <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] uppercase text-subtext0">{props.format}</span>
    </a>
  ),
})

export const Button = defineComponent({
  name: 'Button',
  description: 'A button that runs an action.',
  props: z.object({ label: z.string(), action: action(), variant: z.enum(['primary', 'secondary', 'danger']).optional() }),
  component: ({ props }) => {
    const trigger = useTriggerAction()
    const isUrl = (props.action as { type?: string })?.type === 'open_url'
    return (
      <button type="button" onClick={() => trigger(props.label, undefined, props.action as never)}
              className={cn('flex items-center gap-1.5 rounded-full px-4 py-1.5 text-xs font-medium',
                props.variant === 'danger' ? 'bg-red/15 text-red hover:bg-red/25'
                  : props.variant === 'secondary' ? 'bg-white/[0.06] text-subtext1 hover:bg-white/[0.1]'
                  : 'bg-green text-crust hover:opacity-90')}>
        {props.label}{isUrl && <ExternalLink className="h-3 w-3" />}
      </button>
    )
  },
})

export const Actions = defineComponent({
  name: 'Actions',
  description: 'A row of buttons.',
  props: z.object({ buttons: z.array(Button.ref) }),
  component: ({ props, renderNode }) => <div className="flex flex-wrap gap-2">{renderNode(props.buttons)}</div>,
})

const Leaf = z.union([Text.ref, MetricRow.ref, Chart.ref, Table.ref, SourceList.ref, Download.ref, Actions.ref])

export const Card = defineComponent({
  name: 'Card',
  description: 'A titled section grouping other components.',
  props: z.object({ title: z.string(), children: z.array(Leaf), subtitle: z.string().optional() }),
  component: ({ props, renderNode }) => (
    <section className="rounded-[20px] border border-white/[0.06] bg-white/[0.02] p-4 space-y-3">
      <header>
        <h3 className="text-sm font-medium text-text">{props.title}</h3>
        {props.subtitle && <p className="text-[11px] text-overlay1">{props.subtitle}</p>}
      </header>
      {renderNode(props.children)}
    </section>
  ),
})

export const Stack = defineComponent({
  name: 'Stack',
  description: 'Root container: components stacked vertically.',
  props: z.object({ children: z.array(z.union([Card.ref, Leaf])) }),
  component: ({ props, renderNode }) => <div className="space-y-3">{renderNode(props.children)}</div>,
})

export const library = createLibrary({
  root: 'Stack',
  components: [Stack, Card, Text, Metric, MetricRow, Chart, Table, SourceList, Download, Button, Actions],
})
