import { parse, compileScript, compileTemplate } from "@vue/compiler-sfc"
import { readFileSync } from "node:fs"
let fail = 0
for (const f of process.argv.slice(2)) {
  const src = readFileSync(f, "utf8")
  const { descriptor, errors } = parse(src, { filename: f })
  if (errors.length) { console.log("PARSE ERR "+f); errors.forEach(e=>console.log("  "+e.message)); fail++; continue }
  try {
    const id = "x"+Math.random().toString(36).slice(2)
    if (descriptor.scriptSetup || descriptor.script) compileScript(descriptor, { id })
    if (descriptor.template) compileTemplate({ source: descriptor.template.content, filename: f, id })
    console.log("OK  "+f)
  } catch (e) { console.log("COMPILE ERR "+f+": "+e.message); fail++ }
}
process.exit(fail ? 1 : 0)
