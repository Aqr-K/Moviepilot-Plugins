/** 记录联邦入口及组件哈希，供本地安装时核对整套 dist。 */
import { createHash } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dist = resolve(frontend, 'dist')
const entryFile = 'assets/remoteEntry.js'
const entry = await readFile(resolve(dist, entryFile), 'utf8')
const source = await readFile(resolve(frontend, '../__init__.py'), 'utf8')
const version = source.match(/plugin_version\s*=\s*['"]([^'"]+)['"]/u)?.[1]
if (!version) throw new Error('无法读取插件版本')
const digest = value => createHash('sha256').update(value).digest('hex')
const modules = {}
for (const name of ['Page', 'Config', 'Dashboard', 'AppPage']) {
  const pattern = new RegExp(`__federation_expose_${name}-[^"'\\s/]+\\.js`, 'u')
  const filename = entry.match(pattern)?.[0]
  if (!filename) throw new Error(`联邦入口缺少 ${name} 组件`)
  const file = `assets/${filename}`
  modules[name] = { file, sha256: digest(await readFile(resolve(dist, file))) }
}
await writeFile(resolve(dist, 'build-info.json'), JSON.stringify({
  pluginId: 'AutomaticSubscriptionAssistant', pluginVersion: version,
  builtAt: new Date().toISOString(), remoteEntry: { file: entryFile, sha256: digest(entry) }, modules,
}, null, 2) + '\n')
console.log(`已写入 dist/build-info.json；Config: ${modules.Config.file}`)
