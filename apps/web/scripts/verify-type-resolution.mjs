/** 检查生成声明的包引用仍能解析，防止缓存位置变化令公共类型退化为 any。 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
const web = fileURLToPath(new URL('..', import.meta.url)), app = process.argv[2]
if (!['core', 'workspace', 'enterprise'].includes(app)) throw new Error('Expected core, workspace or enterprise')
const appRoot = join(web, app), coreTypes = join(web, 'core/node_modules/.cache/nexus-types/core')
const root = app === 'core' ? coreTypes : join(appRoot, 'node_modules/.cache/nexus-types/types')
const raw = ts.readConfigFile(join(appRoot, 'tsconfig.json'), ts.sys.readFile)
const config = ts.parseJsonConfigFileContent(raw.config, ts.sys, appRoot)
const options = { ...config.options, paths: { '@/*': [join(root, '*')], '@nexus-web/core/*': [join(coreTypes, '*')] } }
let checked = 0
for (const file of ts.sys.readDirectory(root, ['.d.ts'])) {
  const tree = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true)
  function visit(node) {
    let specifier
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) specifier = node.moduleSpecifier.text
    else if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument) && ts.isStringLiteral(node.argument.literal)) specifier = node.argument.literal.text
    // Vite client 已声明样式通配模块；无绑定样式导入不承载公共类型。
    const style = specifier && ts.isImportDeclaration(node) && !node.importClause && /\.(css|less|scss|sass)(\?.*)?$/.test(specifier)
    if (specifier && !style && !specifier.startsWith('.') && !specifier.startsWith('node:')) {
      if (!ts.resolveModuleName(specifier, file, options, ts.sys).resolvedModule) throw new Error(`unresolved_declaration_dependency:${app}:${file}:${specifier}`)
      checked++
    }
    ts.forEachChild(node, visit)
  }
  visit(tree)
}
if (!checked) throw new Error(`declaration_output_missing:${app}`)
console.log(`${app}: ${checked} 项声明依赖引用解析通过。`)
