import { codeCommentProse, explanationSectionCode, explanationSectionKind, guiInstructions, splitCoverageNotice, workflowMappingLines } from "@/lib/ai/explanation-presentation"
import { pdfPageUrl } from "@/lib/documents/pdf-page"
import type { ExerciseCitation, PublicExplanation } from "@/lib/socra-ws"

function codeMarkdown(code: string, language?: string) {
  const steps = guiInstructions(code)
  if (steps) return steps.map((step, index) => (index + 1) + ". " + step).join("\n")
  const remarks = codeCommentProse(code, language)
  if (remarks) return remarks.join("\n\n")
  const mapping = workflowMappingLines(code, language)
  if (mapping) return mapping.join("  \n")
  const fence = "~".repeat(Math.max(3, ...Array.from(code.matchAll(/~+/g), (run) => run[0].length + 1)))
  const tag = /^[\w+.-]+$/.test(language ?? "") ? language : ""
  return fence + (tag ?? "") + "\n" + code + "\n" + fence
}

function citationMarkdown(citation: ExerciseCitation) {
  const filename = citation.filename.replace(/[\r\n]+/g, " ").replace(/[\\[\]]/g, "\\$&")
  const page = citation.page_number
  const label = filename + (page ? ", page " + page : "")
  return citation.document_id && Number.isInteger(page) && page! > 0
    ? "- [" + label + "](" + pdfPageUrl(citation.document_id, page!) + ")" : "- " + label
}

export function explanationNoteText(explanation: PublicExplanation): string {
  const definition = explanation.definition?.trim() ?? ""
  const authoredTitle = /^# [^\r\n]+(?:\r?\n|$)/.test(definition)
  const lines = authoredTitle
    ? [definition, explanation.intuition]
    : [`# ${explanation.language === "French" ? "Explication du cours" : "Course explanation"}`, definition, explanation.intuition]
  const course = explanation.course_progress
  if (course) {
    const french = course.language === "French"
    const statusLabels = french ? {
      covered: "Traité", partial: "Partiel", missing: "Manquant", unverifiable: "Non vérifiable", not_yet_generated: "À venir",
    } : {
      covered: "Covered", partial: "Partial", missing: "Missing", unverifiable: "Unverifiable", not_yet_generated: "Not yet generated",
    }
    lines.push(french ? `## Partie ${course.part} sur ${course.total_parts}` : `## Part ${course.part} of ${course.total_parts}`,
      course.sections.map((section) => {
        const title = (section.title || (french ? "Section non identifiée" : "Unidentified section")).replace(/\s+/g, " ")
        const pages = section.start === section.end ? String(section.start) : `${section.start}–${section.end}`
        return `- ${title} (p. ${pages}) · ${statusLabels[section.status]}`
      }).join("\n"))
  }
  for (const section of explanation.sections ?? []) {
    const { code, walkthrough } = explanationSectionCode(section)
    const kind = explanationSectionKind(section.heading)
    lines.push("## " + section.heading)
    if (kind === "reference" && section.citations?.some((citation) =>
      citation.document_id && citation.excerpt && Number.isInteger(citation.page_number) && citation.page_number! > 0
    )) lines.push("> Source reference")
    if (section.content?.trim()) lines.push(section.content)
    if (code) lines.push(codeMarkdown(code, section.code_language))
    for (const item of walkthrough) {
      if (item.code) lines.push(codeMarkdown(item.code, section.code_language))
      if (item.explanation) lines.push(item.explanation)
    }
    if (section.citations?.length) lines.push(section.citations.map(citationMarkdown).join("\n"))
  }
  const example = splitCoverageNotice(explanation.course_example ?? "")
  if (example.notice) lines.push("## Coverage notice", example.notice)
  for (const notice of explanation.coverage_notices ?? []) lines.push("## " + notice.heading, notice.content)
  if (example.body.trim()) lines.push("## Course example", example.body)
  if (explanation.common_pitfalls?.length) lines.push("## Common pitfalls", explanation.common_pitfalls.map((item) => "- " + item).join("\n"))
  if (explanation.check_question?.trim()) lines.push("## Check your understanding", explanation.check_question)
  if (explanation.citations?.length) lines.push("## Course sources", explanation.citations.map(citationMarkdown).join("\n"))
  return lines.filter((line) => line?.trim()).join("\n\n")
}
