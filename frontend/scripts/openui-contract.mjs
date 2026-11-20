// Contract check: parses OpenUI Lang specs (from the Python builder) with the REAL parser and
// the REAL component library, and fails on any parse error, unresolved/orphaned reference or
// dropped component. Usage: node scripts/openui-contract.mjs <specs.json>
// specs.json = [{"name": "...", "lang": "..."}]
import { build } from 'esbuild'
import { readFileSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const out = mkdtempSync(join(tmpdir(), 'openui-contract-'))
const bundle = join(out, 'library.mjs')
await build({
  entryPoints: [join(root, 'src/openui/library.tsx')],
  bundle: true, platform: 'node', format: 'esm', outfile: bundle, jsx: 'automatic',
  loader: { '.css': 'empty' }, logLevel: 'error',
  nodePaths: [join(root, 'node_modules')],
})
const { library } = await import(pathToFileURL(bundle).href)
const { createParser } = await import(pathToFileURL(join(root, 'node_modules/@openuidev/react-lang/dist/index.mjs')).href)
const parser = createParser(library.toJSONSchema(), library.root)

function count(node, acc = { elements: 0, types: new Set() }) {
  if (Array.isArray(node)) node.forEach(n => count(n, acc))
  else if (node && typeof node === 'object') {
    if (node.type === 'element') { acc.elements++; acc.types.add(node.typeName) }
    Object.values(node.props ?? {}).forEach(v => count(v, acc))
  }
  return acc
}

const specs = JSON.parse(readFileSync(process.argv[2], 'utf8'))
let failed = 0
const report = []
for (const s of specs) {
  const r = parser.parse(s.lang)
  const statements = s.lang.split('\n').filter(l => /^\s*\w+\s*=/.test(l)).length
  const c = count(r.root)
  const problems = [
    ...r.meta.errors.map(e => `error: ${JSON.stringify(e)}`),
    ...(r.meta.unresolved.length ? [`unresolved: ${r.meta.unresolved.join(',')}`] : []),
    ...(r.meta.orphaned.length ? [`orphaned: ${r.meta.orphaned.join(',')}`] : []),
    ...(r.meta.incomplete ? ['incomplete'] : []),
    ...(c.elements !== statements ? [`rendered ${c.elements} of ${statements} components`] : []),
  ]
  if (problems.length) failed++
  report.push({ name: s.name, ok: !problems.length, problems, root: r.root })
}
rmSync(out, { recursive: true, force: true })
console.log(JSON.stringify({ failed, report }))
process.exit(failed ? 1 : 0)
