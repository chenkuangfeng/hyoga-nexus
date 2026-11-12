/** 检查源码包的静态导入、导出和动态导入，防止应用互相依赖。 */
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, extname, relative, resolve } from 'node:path'
import ts from 'typescript'

export type WebPackage = 'core' | 'workspace' | 'admin'
const packages: WebPackage[] = ['core', 'workspace', 'admin']

export function forbiddenImport(root: string, owner: WebPackage, file: string, specifier: string): boolean {
  let target: string
  if (specifier.startsWith('@nexus-web/')) {
    const name = specifier.split('/')[1]
    return name !== owner && name !== 'core'
  }
  if (specifier.startsWith('@/')) target = resolve(root, owner, 'src', specifier.slice(2))
  else if (specifier.startsWith('.')) target = resolve(dirname(file), specifier)
  else if (specifier.startsWith('/')) target = specifier
  else return false
  const targetOwner = relative(root, target).split('/')[0]
  return packages.includes(targetOwner as WebPackage) && targetOwner !== owner && targetOwner !== 'core'
}

export function checkBoundaries(root: string): string[] {
  const errors: string[] = []
  function walk(dir: string, owner: WebPackage) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const file = resolve(dir, entry.name)
      if (entry.isDirectory()) { walk(file, owner); continue }
      if (!['.vue', '.ts', '.js', '.mjs'].includes(extname(file))) continue
      const source = readFileSync(file, 'utf8')
      const scripts = extname(file) === '.vue'
        ? [...source.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)].map(match => match[1]).join('\n')
        : source
      const tree = ts.createSourceFile(file, scripts, ts.ScriptTarget.Latest, true)
      function visit(node: ts.Node) {
        let specifier: string | undefined
        if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
          specifier = node.moduleSpecifier.text
        } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) {
          specifier = node.arguments[0].text
        }
        if (specifier && forbiddenImport(root, owner, file, specifier)) errors.push(`${relative(root, file)}: ${specifier}`)
        ts.forEachChild(node, visit)
      }
      visit(tree)
    }
  }
  for (const owner of packages) walk(resolve(root, owner, 'src'), owner)
  return errors
}
