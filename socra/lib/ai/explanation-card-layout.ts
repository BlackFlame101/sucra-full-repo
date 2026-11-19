import { marked, type Token, type Tokens } from "marked"
import { explanationSectionCode, explanationSectionKind, splitCoverageNotice } from "@/lib/ai/explanation-presentation"
import { lexStudyMarkdown } from "@/lib/notebook/document"
import type { ExerciseCitation, PublicExplanation } from "@/lib/socra-ws"

const sectionHeadings = {
  metrics: /^(?:what changes|key metrics|indicateurs cl(?:és|es)|ce qui change)(?:\s|:|$)/iu,
  prerequisites: /^(?:before you begin|prerequisites|avant de commencer|prérequis|قبل البدء|المتطلبات المسبقة)(?:\s|:|$)/iu,
  question: /^(?:question|سؤال)\s+\d+\b/iu,
  phase: /^(?:part(?:ie)?|phase|مرحلة|الجزء)\s+(?:\d+|[ivx]+)\b/iu,
  step: /^(?:step|étape|خطوة)\s+\d+|^(?:setup|installation|prerequisites|prérequis)\b/iu,
  checkpoint: /^(?:checkpoint|screenshot|capture|point de contrôle|لقطة شاشة)(?:\s|:|$)/iu,
  troubleshooting: /^(?:troubleshooting|if (?:.+ )?fails|dépannage|en cas d['’]erreur|استكشاف الأخطاء)(?:\s|:|$)/iu,
  deliverable: /^(?:deliverables?|what to hand in|livrables?|à rendre|التسليمات)(?:\s|:|$)/iu,
  reference: /^(?:expected (?:output|results?)|you should see|résultats? attendus?|النتائج المتوقعة)(?:\s|:|$)/iu,
  formula: /^(?:theorem|statement|formula|what we are proving|théorème|formule|نظرية)(?:\s|:|$)/iu,
  derivation: /^(?:derivation|proof|dérivation|démonstration|برهان)(?:\s|:|$)/iu,
  verification: /^(?:verification|check(?: your work)?|vérification|التحقق)(?:\s|:|$)/iu,
  rule: /^(?:rules?|usage|how to form|règles?|formation|قاعدة)(?:\s|:|$)/iu,
  comparison: /^(?:comparison|right and wrong|correct and incorrect|side.by.side|comparaison|مقارنة)(?:\s|:|$)/iu,
  vocabulary: /^(?:vocabulary|signal words|word list|vocabulaire|mots indices|مفردات)(?:\s|:|$)/iu,
  practice: /^(?:practice|exercises?|quiz|pratique|exercices?|تمارين)(?:\s|:|$)/iu,
  researchQuestion: /^(?:research question|question de recherche|سؤال البحث)(?:\s|:|$)/iu,
  method: /^(?:method(?:ology|s)?|study design|méthodologie|méthodes?|منهجية)(?:\s|:|$)/iu,
  findings: /^(?:findings|key (?:findings|results)|main results|résultats (?:principaux|clés)|النتائج الرئيسية)(?:\s|:|$)/iu,
  evidence: /^(?:supporting evidence|data table|evidence|données|preuves|الأدلة)(?:\s|:|$)/iu,
  interpretation: /^(?:interpretation|interprétation|تفسير)(?:\s|:|$)/iu,
  limitations: /^(?:limitations?|study limits|limites?|القيود)(?:\s|:|$)/iu,
  answer: /^(?:answer|direct answer|definition|réponse|définition|الإجابة)(?:\s|:|$)/iu,
  example: /^(?:example|worked example|exemple|مثال)(?:\s|:|$)/iu,
  takeaway: /^(?:takeaway|key takeaway|in short|à retenir|en bref|الخلاصة)(?:\s|:|$)/iu,
}

export type CardSectionKind = keyof typeof sectionHeadings
export type CardProfile = "guide" | "math" | "language" | "research" | "compact" | "generic"

function headingKind(heading: string): CardSectionKind | null {
  const label = heading.trim().replace(/^\d+[.)]\s+/, "").replace(/^the\s+/i, "")
  const existing = explanationSectionKind(label)
  if (existing === "checkpoint" || existing === "reference") return existing
  return (Object.keys(sectionHeadings) as CardSectionKind[]).find((kind) => sectionHeadings[kind].test(label)) ?? null
}

const answerHeading = /^(?:answer|solution|réponse|corrigé|الإجابة|الحل)(?:\s+\d+)?\s*[:：]?$/iu
const answerLine = /^(?:\*\*|__)(?:answer|solution|réponse|corrigé|الإجابة|الحل)\s*[:：](?:\*\*|__)\s*\S/iu

export function cardMarkdownBlocks(tokens: Token[], kind: CardSectionKind | null, profile: CardProfile) {
  const headings = tokens.filter((token): token is Tokens.Heading => token.type === "heading")
  const shallowestDepth = Math.min(...headings.map((heading) => heading.depth))
  const compare = profile === "language" && (kind === "comparison" || kind === "rule" || kind === "vocabulary")
  const paired = compare && headings.filter((heading) => heading.depth === shallowestDepth).length === 2
  const blocks: { tokens: Token[]; kind?: CardSectionKind; answer?: boolean; column?: boolean }[] = [{ tokens: [] }]

  for (const token of tokens) {
    if (token.type === "heading") {
      const heading = token as Tokens.Heading
      const subKind = headingKind(heading.text)
      const answer = kind === "practice" && answerHeading.test(heading.text.trim())
      const column = paired && heading.depth === shallowestDepth
      if (subKind || answer || column || blocks.at(-1)?.answer) {
        blocks.push({ tokens: [heading], kind: subKind ?? undefined, answer, column })
        continue
      }
    }
    if (profile === "guide" && token.type === "code" && blocks.at(-1)?.kind === "prerequisites") {
      blocks.push({ tokens: [token] }, { tokens: [] })
      continue
    }
    if (kind === "practice" && token.type === "paragraph" && answerLine.test(token.raw)) {
      blocks.push({ tokens: [token], answer: true }, { tokens: [] })
      continue
    }
    blocks.at(-1)!.tokens.push(token)
  }
  return blocks.filter((block) => block.tokens.some((token) => token.type !== "space"))
}

export function canPairSetup(
  left: ReturnType<typeof cardMarkdownBlocks>[number] | undefined,
  right: ReturnType<typeof cardMarkdownBlocks>[number] | undefined,
) {
  if (left?.kind !== "prerequisites" || !right) return false
  const checklist = left.tokens.filter((token) => token.type !== "space" && token.type !== "heading")
  const commands = right.tokens.filter((token) => token.type !== "space" && token.type !== "heading")
  if (checklist.length !== 1 || checklist[0].type !== "list" || commands.length !== 1 || commands[0].type !== "code") return false
  const list = checklist[0] as Tokens.List
  const code = commands[0] as Tokens.Code
  const lines = code.text.split("\n")
  return list.items.length <= 8 && list.raw.length <= 650 &&
    /^(?:powershell|pwsh|ps1|bash|sh|shell|cmd|bat|batch)(?:\s|$)/i.test(code.lang ?? "") &&
    lines.length <= 5 && lines.every((line) => line.length <= 42)
}

export function uniqueCardCitations(citations: ExerciseCitation[] | null | undefined) {
  const sources = new Map<string, ExerciseCitation>()
  for (const citation of citations ?? []) {
    if (!citation?.filename?.trim()) continue
    const page = citation.page_number
    const normalized = Number.isSafeInteger(page) && page! > 0 ? citation : { ...citation, page_number: null }
    const key = citationPageKey(normalized)
    const existing = sources.get(key)
    if (!existing || (!existing.excerpt && normalized.excerpt)) sources.set(key, normalized)
  }
  return [...sources.values()].sort((a, b) =>
    (a.document_id || a.filename).localeCompare(b.document_id || b.filename) ||
    (a.page_number ?? Infinity) - (b.page_number ?? Infinity))
}

export function citationPageKey(citation: ExerciseCitation) {
  return JSON.stringify([citation.document_id || citation.filename, citation.page_number])
}

const requirementNames: Record<string, [string, string, string]> = {
  screenshot: ["Screenshot", "Capture", "لقطة الشاشة"],
  question: ["Question", "Question", "السؤال"],
  appendix: ["Appendix", "Annexe", "الملحق"],
  step: ["Step", "Étape", "الخطوة"],
  install: ["Installation", "Installation", "التثبيت"],
  deliverable: ["Deliverable", "Livrable", "التسليم"],
  exercise: ["Exercise", "Exercice", "التمرين"],
  subquestion: ["Subquestion", "Sous-question", "السؤال الفرعي"],
  table: ["Table", "Tableau", "الجدول"],
  figure: ["Figure", "Figure", "الشكل"],
  rule: ["Rule", "Règle", "القاعدة"],
  vocabulary: ["Vocabulary", "Vocabulaire", "المفردات"],
  checkpoint: ["Checkpoint", "Point de contrôle", "نقطة التحقق"],
  verification: ["Verification", "Vérification", "التحقق"],
  section: ["Section", "Section", "القسم"],
  formula: ["Formula", "Formule", "المعادلة"],
  installation: ["Installation", "Installation", "التثبيت"],
  file: ["Required file", "Fichier requis", "الملف المطلوب"],
  expected_result: ["Expected result", "Résultat attendu", "النتيجة المتوقعة"],
  troubleshooting: ["Troubleshooting", "Dépannage", "استكشاف الأخطاء"],
  warning: ["Warning", "Avertissement", "تحذير"],
  part: ["Part", "Partie", "الجزء"],
  bonus: ["Bonus", "Bonus", "إضافي"],
}

export function coverageCopy(heading: string, notice: string) {
  const text = heading + "\n" + notice
  const language = /[\u0600-\u06ff]/u.test(heading || notice.split("\n")[0]) ? 2
    : /incomplète|couverture|extraits récupérés|non traités|éléments insuffisamment|passages requis/iu.test(text) ? 1 : 0
  const missing = /(?:Insufficiently covered|Exercises not covered|incomplete|éléments insuffisamment|exercices non traités|incomplète|شرح غير مكتمل|التمارين التي لم تُغط|عناصر لم تُغط)/iu.test(text)
  const summary = /^part\s+\d+\s+of\s+\d+\b/i.test(heading) ? heading
    : missing ? ["Explanation incomplete", "Explication incomplète", "شرح غير مكتمل"][language]
      : ["Source coverage is limited", "Couverture des sources limitée", "تغطية المصادر محدودة"][language]
  const detail = notice.replace(/(^|[\s,;(])([a-z][a-z_-]*):(?=\S)([^\s,;()]+)/g,
    (match, prefix: string, kind: string, id: string) => {
      const labels = Object.hasOwn(requirementNames, kind) ? requirementNames[kind] : undefined
      const opaque = /^[a-f0-9]{16,}(?:\.\s*$|$)/i.test(id)
      if (opaque) return prefix + (labels?.[language] ?? ["Course requirement", "Élément du cours", "عنصر من الدرس"][language])
      return labels ? `${prefix}${labels[language]} ${id}` : match
    })
  return { summary, detail }
}

export function coverageHighlights(detail: string) {
  const items = detail.split(/\r?\n/).flatMap((line) => {
    const match = /^- \*\*([^*]+)\*\*\s+[—–-]\s+(.+?\(p\. \d+\))(?:\s+[—–-]\s+.*)?$/u.exec(line)
    return match ? [`${match[1]} — ${match[2]}`] : []
  })
  if (items.length) return items.slice(0, 3).join(" · ")
  const count = detail.match(/\((\d+)\)[.:]/)?.[1]
  const legacy = count && detail.match(/\(\d+\):\s*(.+)/)?.[1]
  return legacy && legacy.length <= 150 ? legacy : count ? `(${count})` : ""
}

function markdown(content = "") {
  const tokens = lexStudyMarkdown(content)
  const tasks = new Set<Tokens.ListItem>()
  let math = 0
  let hasTable = false
  const kinds = new Set<CardSectionKind>()
  marked.walkTokens(tokens, (token) => {
    if (token.type === "list_item" && (token as Tokens.ListItem).task) tasks.add(token as Tokens.ListItem)
    if (token.type === "blockMath" || token.type === "inlineMath") math++
    if (token.type === "table") hasTable = true
    if (token.type === "heading") {
      const kind = headingKind((token as Tokens.Heading).text)
      if (kind) kinds.add(kind)
    }
  })
  const lineEndings = content.match(/\r\n|\n|\r/g)
  const firstEnding = lineEndings?.[0]
  const codeLineEnding: "\r\n" | "\r" | undefined = (firstEnding === "\r\n" || firstEnding === "\r") &&
    lineEndings?.every((ending) => ending === firstEnding) ? firstEnding : undefined
  return { content, tokens, tasks, kinds, math, hasTable, codeLineEnding }
}

export type CardMarkdown = ReturnType<typeof markdown>

function plainInline(tokens: Token[]): string {
  return tokens.map((token) => {
    const inline = token as Tokens.Generic
    return inline.tokens ? plainInline(inline.tokens) : inline.text ?? inline.latex ?? ""
  }).join("")
}

export function explanationCardLayout(explanation: PublicExplanation) {
  const example = splitCoverageNotice(explanation.course_example ?? "")
  const notices = (explanation.coverage_notices ?? []).map((notice) => ({ ...notice, citations: [] as ExerciseCitation[] }))
  if (example.notice) notices.push({ heading: "", content: example.notice, citations: [] })
  const sections = (explanation.sections ?? []).flatMap((section, index) => {
    const heading = section.heading?.trim() ?? ""
    const citations = uniqueCardCitations(section.citations)
    if (explanationSectionKind(heading) === "notice") {
      notices.push({ heading, content: section.content ?? "", citations })
      return []
    }
    const { notice, body } = splitCoverageNotice(section.content ?? "")
    if (notice) notices.push({ heading: "", content: notice, citations: [] })
    const source = { ...section, content: body }
    const text = markdown(body)
    const lead = text.tokens.find((token): token is Tokens.Paragraph => token.type === "paragraph")
    const words = lead ? plainInline(lead.tokens).trim().split(/\s+/) : []
    const summary = words.slice(0, 16).join(" ") + (words.length > 16 ? "…" : "")
    const marker = citations.length && section.covers?.length === 1 ? section.covers[0] : ""
    const metadataKind = /^(?:screenshot|question):\d+$/.test(marker)
      ? marker.startsWith("screenshot:") ? "checkpoint" : "question" : null
    return [{ index, heading, citations, kind: headingKind(heading) ?? metadataKind, text, summary,
      ...explanationSectionCode(source), language: section.code_language }]
  })
  const definition = markdown(explanation.definition ?? "")
  const intuition = markdown(explanation.intuition ?? "")
  // A leading authored H1 can act as the card title. Keep all ordinary headings in place.
  const leading = [definition, intuition, sections[0]?.text].find((block) => block?.content.trim())
  const titleToken = leading?.tokens[0]
  const title = titleToken?.type === "heading" && (titleToken as Tokens.Heading).depth === 1 ? titleToken as Tokens.Heading : undefined
  if (title && leading) leading.tokens = leading.tokens.slice(1)

  const kinds = new Set(sections.flatMap(({ kind, text }) => [...(kind ? [kind] : []), ...text.kinds]))
  const count = (...candidates: CardSectionKind[]) => candidates.filter((kind) => kinds.has(kind)).length
  const practical = count("phase", "step", "checkpoint", "troubleshooting", "deliverable", "prerequisites")
  const research = count("researchQuestion", "method", "findings", "evidence", "interpretation", "limitations")
  const language = count("rule", "comparison", "vocabulary", "practice")
  const math = definition.math + intuition.math + sections.reduce((total, section) => total + section.text.math, 0)
  const length = definition.content.length + intuition.content.length + example.body.length +
    sections.reduce((total, section) => total + section.text.content.length + section.code.length +
      section.walkthrough.reduce((subtotal, item) => subtotal + (item.code?.length ?? 0) + (item.explanation?.length ?? 0), 0), 0)
  const brief = explanation.presentation === "brief" || explanation.presentation == null && sections.length === 1 &&
    /^(?:summary|résumé|ملخص)$/iu.test(sections[0].heading) && length <= 1400 &&
    !sections[0].code && !sections[0].text.tokens.some((token) => token.type === "code")
  const profile: CardProfile = brief ? "compact"
    : explanation.presentation === "walkthrough" || explanation.presentation == null &&
      (practical >= 2 || (practical >= 1 && kinds.has("reference"))) ? "guide"
    : research >= 2 ? "research"
    : kinds.has("derivation") || (math > 0 && count("formula", "verification")) || math >= 3 ? "math"
    : kinds.has("vocabulary") || language >= 2 ? "language"
    : explanation.presentation == null && sections.length <= 3 && length <= 1100 &&
      sections.every(({ text, code }) => !code && !text.hasTable) ? "compact"
    : "generic"
  return {
    profile, brief, title, definition, intuition, sections, notices, example: markdown(example.body),
    citations: uniqueCardCitations(explanation.citations),
    collapsible: profile === "guide" && sections.length >= 3 && (length >= 1400 || sections.length >= 5),
  }
}

type CardSection = ReturnType<typeof explanationCardLayout>["sections"][number]

export function groupGuideSections(sections: CardSection[]) {
  const groups: { section: CardSection; children: CardSection[]; phaseLabel?: string }[] = []
  let phase: (typeof groups)[number] | undefined
  const prefixes = sections.map(({ heading }) => /^(part(?:ie)?\s+(?:\d+|[ivxlcdm]+)\s*[:.]\s*[^—–]+?)\s+[—–-]\s+(.+)$/iu.exec(heading))
  const prefixKey = (match: RegExpExecArray | null | undefined) => match?.[1].toLocaleLowerCase()
  for (const [position, section] of sections.entries()) {
    const prefix = prefixes[position]
    if (prefix && (prefixKey(prefixes[position - 1]) === prefixKey(prefix) || prefixKey(prefixes[position + 1]) === prefixKey(prefix))) {
      phase = undefined
      groups.push({ section: { ...section, heading: prefix[2] }, children: [],
        phaseLabel: prefixKey(prefixes[position - 1]) === prefixKey(prefix) ? undefined : prefix[1] })
      continue
    }
    if (section.kind === "phase" || section.kind === "deliverable") phase = undefined
    if (phase) {
      phase.children.push(section)
      continue
    }
    const group = { section, children: [] as CardSection[] }
    groups.push(group)
    // A heading-only phase explicitly introduces the steps that follow it.
    if (section.kind === "phase" && !section.code && !section.walkthrough.length &&
        section.text.tokens.every((token) => token.type === "space")) phase = group
  }
  return groups
}
