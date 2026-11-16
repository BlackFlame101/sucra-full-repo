import { marked, type Tokens } from "marked"
import { lexStudyMarkdown } from "@/lib/notebook/document"
import type { ExplanationSection } from "@/lib/socra-ws"

export function codeLabel(language?: string) {
  const tag = language?.trim().split(/\s+/)[0] ?? ""
  switch (tag.toLowerCase()) {
    case "powershell": case "pwsh": case "ps1": return "Run in PowerShell"
    case "python": case "py": return "Python code"
    case "bash": return "Bash"
    case "sh": case "shell": return "Shell"
    case "bat": case "batch": case "cmd": return "Windows Command Prompt"
    case "js": case "javascript": return "JavaScript"
    case "ts": case "typescript": return "TypeScript"
    case "sql": return "SQL"
    default: return tag || "Code"
  }
}

export function guiInstructions(code: string): string[] | null {
  const lines = code.trim().split(/\r?\n/).filter((line) => line.trim())
  const steps = lines.map((line) => /^\s*(?:#|\/\/|--)\s*(?:\d+[.)]\s+)?(.+)$/.exec(line)?.[1])
  return steps.length && steps.every((step): step is string => !!step &&
    /^(?:(?:open|click|select|choose|drag|drop|double-click|right-click|navigate|press|ouvrez|cliquez|sélectionnez|choisissez|glissez|appuyez|افتح|انقر|اختر|اضغط)(?:\s|$))/iu.test(step))
    ? steps : null
}

export function codeCommentProse(code: string, language?: string): string[] | null {
  const tag = language?.trim().split(/\s+/)[0]?.toLowerCase() ?? ""
  if (tag && !/^(?:python|py|powershell|pwsh|ps1|bash|sh|shell)$/.test(tag)) return null
  const lines = code.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  if (!lines.length || !lines.every((line) => /^#(?!\!)/.test(line))) return null
  return lines.map((line) => line.replace(/^#+\s*/, "")).filter(Boolean)
}

export function workflowMappingLines(value: string, language?: string): string[] | null {
  if (!/^(?:text|plaintext|txt)$/i.test(language?.trim().split(/\s+/)[0] ?? "")) return null
  const lines = value.trim().split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  if (!lines.length || lines.some((line) => line.length > 180)) return null
  const label = /^[\p{Lu}][\p{L}\d]*(?: [\p{Lu}\d][\p{L}\d]*){0,4}(?: \([\p{L}\d ]+\))?$/u
  const arrows = lines.every((line) => {
    const path = line.split(/\s+(?:->|→|⇒)\s+/u)
    return path.length >= 3 && path.slice(1).every((step) => label.test(step))
  })
  const labels = lines.length >= 2 && lines.length <= 8 && lines.every((line) => label.test(line)) &&
    lines.some((line) => / (?:Reader|Writer|Viewer|Widget|Node|Table)(?: \(|$)/.test(line))
  return arrows || labels ? lines : null
}

function includesCode(block: string, snippet: string) {
  const normalize = (value: string) => value.trim().split(/\r?\n/).map((line) => line.trim()).join("\n")
  return ("\n" + normalize(block) + "\n").includes("\n" + normalize(snippet) + "\n")
}

export function explanationSectionCode(section: ExplanationSection) {
  const inline: string[] = []
  marked.walkTokens(lexStudyMarkdown(section.content ?? ""), (token) => {
    if (token.type === "code") inline.push((token as Tokens.Code).text)
  })
  const code = section.code?.trim() && !inline.some((block) => includesCode(block, section.code!))
    ? section.code : ""
  const shown = code ? [...inline, code] : inline
  const walkthrough = (section.walkthrough ?? []).map((item) => {
    if (!item.code?.trim() || shown.some((block) => includesCode(block, item.code))) return { ...item, code: "" }
    shown.push(item.code)
    return item
  })
  return { code, walkthrough }
}

const noticeHeading = /^(?:incomplete\b|limited source coverage\b|coverage check\b|part\s+\d+\s+of\s+\d+\b|explication incomplète\b|couverture des sources limitée\b|vérification de la couverture\b|شرح غير مكتمل|تغطية محدودة للمصادر|التحقق من التغطية)/iu
const noticeLine = /^(?:Exercises not covered:|Insufficiently covered requirements\.|Checked against retrieved excerpts only\.|Requirements with evidence outside the supplied excerpts:|Exercices non traités\s*:|Éléments insuffisamment couverts\.|Vérification limitée aux extraits récupérés\.|Passages requis absents du contexte\s*:|التمارين التي لم تُغطَّ|عناصر لم تُغطَّ بشكل كافٍ|اقتصر التحقق على المقتطفات المسترجعة|عدد المتطلبات التي لم تُرسل أدلتها)/iu

export function explanationSectionKind(heading: string) {
  if (noticeHeading.test(heading.trim())) return "notice"
  if (/^(?:screenshot(?:\s+checkpoint)?\b|capture(?:\s+d[’']écran)?\b|لقطة شاشة)/iu.test(heading.trim())) return "checkpoint"
  if (/^(?:source reference results\b|expected (?:results|outputs)\b|résultats (?:de référence|attendus)\b|النتائج المرجعية)/iu.test(heading.trim())) return "reference"
  return null
}

export function splitCoverageNotice(content: string) {
  const paragraphs = content.split(/(\r?\n\r?\n|\r\r)/)
  let index = 0
  while (index < paragraphs.length && noticeLine.test(paragraphs[index])) index += 2
  return { notice: paragraphs.slice(0, Math.max(index - 1, 0)).join(""), body: paragraphs.slice(index).join("") }
}
