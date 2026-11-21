/** 生成原生 TypeScript 引用工程；每个业务源文件恰为一个工程的根文件，不跳过模板。 */
import { readFileSync, writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { dirname, extname, resolve, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { parse } from '@vue/compiler-sfc'

const web = fileURLToPath(new URL('..', import.meta.url)), app = process.argv[2]
if (!['workspace', 'enterprise'].includes(app)) throw new Error('Expected workspace or enterprise')
const appRoot = join(web, app), sourceRoot = join(appRoot, 'src'), configPath = join(appRoot, 'tsconfig.json')
const raw = ts.readConfigFile(configPath, ts.sys.readFile)
if (raw.error) throw new Error(ts.flattenDiagnosticMessageText(raw.error.messageText, '\n'))
const config = ts.parseJsonConfigFileContent(raw.config, ts.sys, appRoot, {}, configPath, undefined, [{ extension: '.vue', isMixedContent: true, scriptKind: ts.ScriptKind.Deferred }])
if (config.errors.length) throw new Error(config.errors.map(e => ts.flattenDiagnosticMessageText(e.messageText, '\n')).join('\n'))
const files = config.fileNames.map(f => f.replaceAll('\\', '/')).filter(f => !f.endsWith('.d.ts')).sort(), fileSet = new Set(files)
const globals = config.fileNames.map(f => f.replaceAll('\\', '/')).filter(f => f.endsWith('.d.ts'))
const coreTypes = join(web, 'core/node_modules/.cache/nexus-types/core')
// core 的全局增强在完整应用程序中始终可见，拆分后也保留同样的可见性。
function collectGlobals(dir) {
  for (const file of ts.sys.readDirectory(dir, ['.d.ts'])) if (/declare\s+global\s*\{/.test(readFileSync(file, 'utf8'))) globals.push(file)
}
collectGlobals(coreTypes)
const code = new Map(), dependencies = new Map()
function localFile(specifier, importer) {
  let target
  if (specifier.startsWith('@/')) target = join(sourceRoot, specifier.slice(2))
  else if (specifier.startsWith('.')) target = resolve(dirname(importer), specifier)
  else return
  const base = target.replace(/\.(m?js)$/, '.ts')
  const candidates = [base, `${base}.ts`, `${base}.vue`, `${base}.d.ts`, join(base, 'index.ts')]
  return candidates.map(f => f.replaceAll('\\', '/')).find(f => fileSet.has(f))
}
for (const file of files) {
  const source = readFileSync(file, 'utf8')
  let script = source
  if (extname(file) === '.vue') {
    const { descriptor, errors } = parse(source, { filename: file, sourceMap: false })
    if (errors.length) throw new Error(`Invalid SFC: ${file}`)
    script = [descriptor.script?.content, descriptor.scriptSetup?.content].filter(Boolean).join('\n')
  }
  code.set(file, source.length)
  const tree = ts.createSourceFile(file, script, ts.ScriptTarget.Latest, true), deps = new Set()
  function visit(node) {
    let specifier
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) specifier = node.moduleSpecifier.text
    else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) specifier = node.arguments[0].text
    else if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument) && ts.isStringLiteral(node.argument.literal)) specifier = node.argument.literal.text
    if (specifier) { const target = localFile(specifier, file); if (target) deps.add(target) }
    ts.forEachChild(node, visit)
  }
  visit(tree); dependencies.set(file, deps)
}
// Tarjan：相互引用的文件必须在同一个原生工程中检查，不能用声明切断循环约束。
let next = 0
const indices = new Map(), low = new Map(), active = new Set(), stack = [], components = []
function connect(file) {
  indices.set(file, next); low.set(file, next++); stack.push(file); active.add(file)
  for (const dep of dependencies.get(file)) {
    if (!indices.has(dep)) { connect(dep); low.set(file, Math.min(low.get(file), low.get(dep))) }
    else if (active.has(dep)) low.set(file, Math.min(low.get(file), indices.get(dep)))
  }
  if (low.get(file) === indices.get(file)) {
    const component = []; let member
    do { member = stack.pop(); active.delete(member); component.push(member) } while (member !== file)
    components.push(component.sort())
  }
}
for (const file of files) if (!indices.has(file)) connect(file)
// Tarjan 结果按依赖优先排列；按源文件体积组合，避免模板虚拟代码在同一进程累积。
const groups = []; let group = [], bytes = 0
for (const component of components) {
  const size = component.reduce((n, f) => n + code.get(f), 0)
  if (group.length && (bytes + size > 120_000 || group.length + component.length > 28)) { groups.push(group); group = []; bytes = 0 }
  group.push(...component); bytes += size
}
if (group.length) groups.push(group)
const covered = groups.flat()
if (covered.length !== files.length || new Set(covered).size !== files.length) throw new Error('type_project_coverage_invalid')
const cache = join(appRoot, 'node_modules/.cache/nexus-types')
rmSync(cache, { recursive: true, force: true }); mkdirSync(cache, { recursive: true })
const owner = new Map(groups.flatMap((g, i) => g.map(f => [f, i])))
const projects = groups.map((g, i) => join(cache, `${i}.json`))
for (const [i, roots] of groups.entries()) {
  const refs = new Set()
  for (const f of roots) for (const dep of dependencies.get(f)) if (owner.get(dep) !== i) refs.add(owner.get(dep))
  if ([...refs].some(n => n >= i)) throw new Error('type_project_dependency_order_invalid')
  // 本工程根文件始终解析到源文件，重建时也不能把自身旧声明当作输入。
  const ownPaths = {}
  for (const file of roots) {
    const name = relative(sourceRoot, file).replaceAll('\\', '/')
    ownPaths[`@/${name}`] = [file]
    ownPaths[`@/${name.replace(/\.(tsx?|vue)$/, '')}`] = [file]
    if (/\/index\.tsx?$/.test(name)) ownPaths[`@/${name.replace(/\/index\.tsx?$/, '')}`] = [file]
  }
  const options = {
    extends: configPath,
    compilerOptions: { composite: true, noEmit: false, declaration: true, emitDeclarationOnly: true, noEmitOnError: true,
      rootDir: sourceRoot, outDir: join(cache, 'types'), tsBuildInfoFile: join(cache, `${i}.tsbuildinfo`), disableSourceOfProjectReferenceRedirect: true,
      paths: { ...ownPaths, '@/*': [join(cache, 'types/*'), join(sourceRoot, '*')], '@nexus-web/core/*': [join(coreTypes, '*')] } },
    files: [...globals, ...roots], include: [], exclude: [],
    references: [{ path: join(web, 'core/tsconfig.types.json') }, ...[...refs].sort((a,b) => a-b).map(n => ({ path: projects[n] }))],
  }
  writeFileSync(projects[i], JSON.stringify(options, null, 2))
}
writeFileSync(join(cache, 'manifest.json'), JSON.stringify({ app, projects, files, groups: groups.map(g => ({ count: g.length, bytes: g.reduce((n,f) => n + code.get(f), 0) })) }, null, 2))
console.log(`${app}: ${files.length} 个源文件，${groups.length} 个严格检查工程（含所有 Vue 模板）。`)
