/** 生产资产专有回归：实际加载预打包运行时，执行图表与 PDF worker。 */
import { readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { test, expect } from './fixtures'
const require = createRequire(new URL('../workspace/package.json', import.meta.url))
function asset(prefix: string): string {
  const files = readdirSync(new URL('../workspace/dist/assets/vendor/', import.meta.url)).filter(f => f.startsWith(prefix) && f.endsWith('.js'))
  if (files.length !== 1) throw new Error(`Expected one production asset: ${prefix}`)
  return `/assets/vendor/${files[0]}`
}
function smallPdf(): string {
  const content = 'BT /F1 12 Tf 20 100 Td (Hello) Tj ET'
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${content.length} >>\nstream\n${content}\nendstream`]
  let source = '%PDF-1.4\n'; const offsets = [0]
  for (const [i, object] of objects.entries()) { offsets.push(source.length); source += `${i + 1} 0 obj\n${object}\nendobj\n` }
  const xref = source.length
  source += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  for (const offset of offsets.slice(1)) source += `${String(offset).padStart(10, '0')} 00000 n \n`
  return `${source}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`
}

test('生产图表和 PDF worker 正常执行，VueOffice 模块能够加载', async ({ page }) => {
  const version = require('mermaid/package.json').version as string
  await page.goto('/login'); await expect(page.locator('input[type="password"]')).toBeVisible()
  const result = await page.evaluate(async ({ mermaidUrl, pdfUrl, workerUrl, officeUrl, highlightUrl, katexUrl, xlsxUrl, data }) => {
    const { default: mermaid } = await import(mermaidUrl)
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' })
    const diagram = await mermaid.render('production-diagram', 'flowchart LR\n A[Start] --> B[Done]')
    const pdf = await import(pdfUrl)
    pdf.GlobalWorkerOptions.workerSrc = workerUrl
    const loading = pdf.getDocument({ data: Uint8Array.from(data, c => c.charCodeAt(0)), wasmUrl: `${location.origin}/pdfjs/wasm/` })
    const pdfDoc = await loading.promise
    const first = await pdfDoc.getPage(1), text = await first.getTextContent()
    const office = await import(officeUrl)
    const highlight = await import(highlightUrl), katex = await import(katexUrl), xlsx = await import(xlsxUrl)
    const workbook = xlsx.read('a,b\n1,2', { type: 'string' })
    const cells = xlsx.utils.sheet_to_json(workbook.Sheets[workbook.SheetNames[0]])
    const result = { diagram: diagram.svg.includes('Start') && diagram.svg.includes('Done'), pages: pdfDoc.numPages,
      text: text.items.map((item: { str?: string }) => item.str || '').join(''), office: typeof office.default.setup,
      highlight: !!highlight.default.getLanguage('mathematica') && highlight.default.highlight('const x = 1', { language: 'typescript' }).value.includes('hljs-keyword'),
      math: katex.default.renderToString('x^2').includes('<math'),
      sheet: JSON.stringify(cells), writable: xlsx.write(workbook, { type: 'array', bookType: 'xlsx' }).byteLength > 0 }
    await loading.destroy()
    return result
  }, { mermaidUrl: `/assets/mermaid-${version}/mermaid.esm.min.js`, pdfUrl: asset('pdfjs-dist-legacy-build-pdf.mjs-'),
    workerUrl: asset('pdfjs-dist-legacy-build-pdf.worker.min.mjs-worker-url-'), officeUrl: asset('-vue-office-pptx-'), highlightUrl: asset('highlight.js-'), katexUrl: asset('katex-'), xlsxUrl: asset('xlsx-'), data: smallPdf() })
  expect(result).toEqual({ diagram: true, pages: 1, text: 'Hello', office: 'function', highlight: true, math: true, sheet: '[{"a":1,"b":2}]', writable: true })
})
