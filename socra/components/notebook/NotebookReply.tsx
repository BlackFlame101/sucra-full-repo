"use client"

import { memo, useMemo, useState } from "react"
import type { Token, Tokens } from "marked"
import katex from "katex"
import { codeCommentProse, codeLabel, guiInstructions, workflowMappingLines } from "@/lib/ai/explanation-presentation"
import { Button } from "@/components/ui/button"
import { lexStudyMarkdown, safeNoteLink } from "@/lib/notebook/document"

export function StudyCopy({ value, label, french, selectFallback }: {
  value: string; label: string; french?: boolean; selectFallback?: boolean
}) {
  const [status, setStatus] = useState("")
  const [selectText, setSelectText] = useState(false)
  const button = <Button type="button" size="sm" variant="ghost" className={selectFallback ? "min-h-11" : undefined} onClick={async () => {
    try {
      await navigator.clipboard.writeText(value)
      setStatus(french ? "Copié" : "Copied")
      if (selectText) setSelectText(false)
    }
    catch {
      if (selectFallback) {
        setSelectText(true)
        setStatus(french ? "Copier le texte sélectionné" : "Copy the selected text")
      } else setStatus(french ? "Copie indisponible" : "Copy unavailable")
    }
  }}><span aria-live="polite">{status || label}</span></Button>
  if (!selectText) return button
  return <div className="min-w-0">{button}<textarea readOnly value={value}
    aria-label={french ? "Texte à copier" : "Text to copy"} rows={3}
    className="w-full min-w-0 rounded-md border p-2 text-sm focus-visible:outline-2 focus-visible:outline-ring"
    ref={(element) => { element?.focus({ preventScroll: true }); element?.select() }} /></div>
}

export type StudyMarkdownPresentation = {
  french?: boolean
  selectCopyFallback?: boolean
  checklist?: (item: Tokens.ListItem) => { checked: boolean; toggle: (checked: boolean) => void } | undefined
  codeLineEnding?: "\r\n" | "\r"
  copyTables?: boolean
  metricSummary?: boolean
  documentStyle?: boolean
  citation?: (id: string) => { label: string; title: string; href?: string } | undefined
}

function render(tokens: Token[], inline = false, presentation?: StudyMarkdownPresentation): React.ReactNode {
  const renderChildren = (items: Token[], isInline = false) => render(items, isInline, presentation)
  return tokens.map((token, key) => {
    const t = token as Tokens.Generic
    const children = () => renderChildren(t.tokens ?? [], true)
    switch (t.type) {
      case "space": return null
      case "sourceCitation": {
        const reference = presentation?.citation?.(t.citationId)
        if (!reference) return <span key={key}>{t.raw}</span>
        const style = "ms-1 inline-block whitespace-nowrap align-baseline text-xs font-medium text-secondary underline underline-offset-2"
        return reference.href ? <a key={key} href={reference.href} className={style} title={reference.title}
          target="_blank" rel="noopener noreferrer">{reference.label}</a>
          : <span key={key} title={reference.title} className="ms-1 text-xs text-muted-foreground">{reference.label}</span>
      }
      case "inlineMath": case "blockMath": {
        // KaTeX escapes input and runs with trust disabled.
        const displayMode = t.type === "blockMath"
        const MathElement = displayMode ? "div" : "span"
        return <MathElement key={key} className={displayMode
          ? `overflow-x-auto ${presentation ? "[&_.katex-display]:w-max [&_.katex-display]:min-w-full" : ""}`
          : undefined}
          tabIndex={presentation && displayMode ? 0 : undefined}
          role={presentation && displayMode ? "group" : undefined}
          aria-label={presentation && displayMode ? "Equation" : undefined}
          dangerouslySetInnerHTML={{ __html: katex.renderToString(t.latex, { displayMode, throwOnError: false, trust: false }) }} />
      }
      case "heading": {
        if (presentation?.documentStyle) {
          const Heading = (["h1", "h2", "h3", "h4", "h5", "h6"] as const)[Math.min(6, Math.max(1, t.depth)) - 1]
          const typography = t.depth === 1 ? "text-3xl font-semibold sm:text-4xl" :
            t.depth === 2 ? "pt-5 text-2xl font-semibold" : "pt-3 text-xl font-semibold"
          return <Heading key={key} className={"font-serif leading-tight tracking-tight " + typography}>{children()}</Heading>
        }
        const Heading = t.depth === 1 ? "h3" : t.depth === 2 ? "h4" : "h5"
        return <Heading key={key} className="font-serif text-lg font-semibold">{children()}</Heading>
      }
      case "paragraph": return <p key={key}>{children()}</p>
      case "strong": return <strong key={key}>{children()}</strong>
      case "em": return <em key={key}>{children()}</em>
      case "del": return <del key={key}>{children()}</del>
      case "br": return <br key={key} />
      case "hr": return <hr key={key} />
      case "codespan": return <code key={key} className="rounded bg-muted px-1">{t.text}</code>
      case "link": return safeNoteLink(t.href)
        ? <a key={key} href={t.href} target="_blank" rel="noopener noreferrer" className="text-secondary underline">{children()}</a>
        : <span key={key}>{children()}</span>
      case "blockquote": return <blockquote key={key} className="space-y-2 border-l-2 border-secondary pl-3">{renderChildren(t.tokens ?? [])}</blockquote>
      case "list": {
        const List = t.ordered ? "ol" : "ul"
        const items = t.items as Tokens.ListItem[]
        const checklist = presentation?.checklist && !t.ordered && items.every((item) => item.task)
        return <List key={key} start={t.ordered ? t.start : undefined} className={checklist ? "space-y-2.5" : `space-y-1 ${presentation ? "ps-5" : "pl-5"} ${t.ordered ? "list-decimal" : "list-disc"}`}>
          {items.map((item, index) => {
            const task = item.task ? presentation?.checklist?.(item) : undefined
            const body = renderChildren(item.tokens)
            return task ? <li key={index} className="break-inside-avoid" data-explanation-task>
              <div className="flex items-start gap-2.5">
                <input type="checkbox" aria-label={item.text.split("\n")[0] || `Task ${index + 1}`}
                  className="mt-1 size-4 shrink-0 accent-primary" checked={task.checked}
                  onChange={(event) => task.toggle(event.currentTarget.checked)} />
                <div className="min-w-0">{body}</div>
              </div>
            </li> : <li key={index}>{item.task && <span aria-label={item.checked ? "Completed" : "Incomplete"}>{item.checked ? "☑ " : "☐ "}</span>}{body}</li>
          })}
        </List>
      }
      case "checkbox": return presentation ? null : <span key={key}>{t.raw}</span>
      case "table": {
        const table = token as Tokens.Table
        const copy = presentation?.copyTables && <div className="mt-1 print:hidden">
          <StudyCopy value={presentation.codeLineEnding ? table.raw.replaceAll("\n", presentation.codeLineEnding) : table.raw}
            label="Copy as Markdown" />
        </div>
        const metricRows = presentation?.metricSummary && table.header.length === 2 &&
          /^(?:metric|measure|mesure|indicateur)$/iu.test(table.header[0].text) &&
          /^(?:value|valeur)$/iu.test(table.header[1].text) && table.rows.length >= 2 && table.rows.length <= 4 &&
          table.rows.every(([label, value]) => label.text.trim() && value.tokens.every(({ type }) => type === "text") &&
            /^[+−-]?\d+(?:[.,]\d+)?(?:\s*%)?$/u.test(value.text))
        if (metricRows) return <div key={key}>
          <dl className={`grid gap-2 @md/card:grid-cols-2 ${table.rows.length > 2 ? "@xl/card:grid-cols-3" : ""}`}>
            {table.rows.map(([label, value], index) => <div key={index} className="flex min-w-0 flex-col rounded-lg border p-3">
              <dt className="text-xs text-muted-foreground">{renderChildren(label.tokens, true)}</dt>
              <dd className="order-first text-xl font-semibold tabular-nums">{value.text}</dd>
            </div>)}
          </dl>
          {copy}
        </div>
        return <div key={key} className="min-w-0">
          <div className="overflow-x-auto print:overflow-visible" tabIndex={presentation ? 0 : undefined}
          role={presentation ? "region" : undefined} aria-label={presentation ? "Data table" : undefined}>
          <table className="w-full border-collapse text-sm">
          <thead><tr>{table.header.map((cell, index) => <th scope="col" key={index} className="border bg-muted p-2 text-left">{renderChildren(cell.tokens, true)}</th>)}</tr></thead>
          <tbody>{table.rows.map((row, index) => <tr key={index}>{row.map((cell, column) => <td key={column} className="border p-2 align-top">{renderChildren(cell.tokens, true)}</td>)}</tr>)}</tbody>
          </table></div>
          {copy}
        </div>
      }
      case "code": return <StudyCode key={key} value={presentation?.codeLineEnding ? t.text.replaceAll("\n", presentation.codeLineEnding) : t.text}
        language={presentation?.documentStyle ? t.lang?.split(/\s+/)[0] : t.lang}
        cellId={presentation?.documentStyle ? /(?:^|\s)cell:([a-f0-9]{24})(?:\s|$)/.exec(t.lang ?? "")?.[1] : undefined}
        french={presentation?.french} selectCopyFallback={presentation?.selectCopyFallback} />
      case "image": case "escape": return <span key={key}>{t.text}</span>
      case "text": return t.tokens?.length ? <span key={key}>{renderChildren(t.tokens, true)}</span>
        : inline ? t.text : <span key={key}>{t.text}</span>
      default: return <span key={key}>{t.raw}</span>
    }
  })
}

export function StudyCode({ value, language, french, selectCopyFallback, cellId }: {
  value: string; language?: string; french?: boolean; selectCopyFallback?: boolean; cellId?: string
}) {
  const steps = guiInstructions(value)
  if (steps) return <ol className="list-decimal space-y-1 pl-5">{steps.map((step, index) =>
    <li key={index}>{step}</li>)}</ol>
  const remarks = codeCommentProse(value, language)
  if (remarks) return <div>{remarks.map((line, index) => <p key={index}>{line}</p>)}</div>
  const mapping = workflowMappingLines(value, language)
  if (mapping) return <div className="space-y-1 [overflow-wrap:anywhere]">
    {mapping.map((line, index) => <p key={index}>{line}</p>)}
  </div>
  const plain = /^(?:text|plaintext|plain|txt|output|result|math)$/i.test(language?.trim() ?? "")
  const shell = plain && value.trim().split(/\r?\n/).every((line) =>
    /^(?:python(?:3|\.exe)?\s+-m\s+\S+|(?:pip|uv|npm|git)\s+(?:install|run|add|status|diff|log|show|clone)\b)/.test(line.trim()))
  if (plain && !shell) {
    return <pre tabIndex={0} className="min-w-0 overflow-x-auto whitespace-pre-wrap rounded-lg border bg-muted/50 p-3 text-sm">{value}</pre>
  }
  return <div className="min-w-0 rounded-lg border bg-muted/50" data-code-cell={cellId}>
    <div className={`flex items-center justify-between gap-2 px-3 text-xs text-muted-foreground ${selectCopyFallback ? "flex-wrap" : ""}`}>
      <span>{shell ? (french ? "Commande" : "Shell command") : codeLabel(language)}</span>
      <StudyCopy value={value} label={french ? "Copier le code" : "Copy code"} french={french} selectFallback={selectCopyFallback} />
    </div>
    <pre tabIndex={0} className="overflow-x-auto whitespace-pre border-t p-3 font-mono text-sm leading-relaxed [overflow-wrap:normal] print:overflow-visible print:whitespace-pre-wrap print:[overflow-wrap:anywhere]"><code>{value}</code></pre>
  </div>
}

export const StudyMarkdown = memo(function StudyMarkdown({ content, tokens, presentation }: {
  content?: string; tokens?: Token[]; presentation?: StudyMarkdownPresentation
}) {
  const body = useMemo(() => render(tokens ?? lexStudyMarkdown(content ?? ""), false, presentation), [content, tokens, presentation])
  return <div className={presentation?.documentStyle ? "min-w-0 space-y-5 leading-7 [overflow-wrap:anywhere]" :
    "min-w-0 space-y-3 [overflow-wrap:anywhere]"}>{body}</div>
})

export const NotebookReply = memo(function NotebookReply({ content, streaming, partial }: {
  content: string; streaming: boolean; partial?: boolean
}) {
  const [collapsed, setCollapsed] = useState(false)
  return <article className="min-w-0 space-y-2 rounded-xl border bg-card/40 px-4 py-3 sm:px-5">
    <h3 className="flex flex-wrap items-center gap-2 text-sm font-medium">Socra Tutor
      {streaming && <span className="text-xs font-normal text-secondary">Responding…</span>}
      {partial && <span className="text-xs font-normal text-muted-foreground">Partial response</span>}
    </h3>
    <div hidden={collapsed} className="text-[15px] leading-relaxed"><StudyMarkdown content={content} /></div>
    {!streaming && <div className="flex flex-wrap items-center gap-1">
      <StudyCopy value={content} label="Copy response" />
      {content.length > 1800 && <Button size="sm" variant="ghost" aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}>{collapsed ? "Expand response" : "Collapse response"}</Button>}
    </div>}
  </article>
})
