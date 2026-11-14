import type { PublicExplanation } from "@/lib/socra-ws"

export function explanationNoteText(explanation: PublicExplanation): string {
  const lines = [`# ${explanation.definition}`, "", explanation.intuition, ""]
  for (const section of explanation.sections ?? []) {
    lines.push(`## ${section.heading}`, section.content)
    if (section.code) lines.push(`\n\`\`\`${section.code_language || ""}\n${section.code}\n\`\`\``)
    for (const item of section.walkthrough ?? []) lines.push(`\n\`\`\`\n${item.code}\n\`\`\`\n${item.explanation}`)
    lines.push("")
  }
  if (explanation.course_example) lines.push("## Course example", explanation.course_example, "")
  if (explanation.common_pitfalls?.length) lines.push("## Common pitfalls", ...explanation.common_pitfalls.map((item) => `- ${item}`), "")
  if (explanation.check_question) lines.push("## Check your understanding", explanation.check_question, "")
  if (explanation.citations?.length) lines.push("## Course sources", ...explanation.citations.map(
    (citation) => `- ${citation.filename}${citation.page_number ? `, page ${citation.page_number}` : ""}`
  ))
  return lines.join("\n")
}
