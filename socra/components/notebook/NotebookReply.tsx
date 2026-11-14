"use client"

import { memo, useMemo, useState } from "react"
import { marked, type Token, type Tokens } from "marked"
import { Button } from "@/components/ui/button"
import { safeNoteLink } from "@/lib/notebook/document"

function Copy({ value, label }: { value: string; label: string }) {
  const [status, setStatus] = useState("")
  return <Button size="sm" variant="ghost" onClick={async () => {
    try { await navigator.clipboard.writeText(value); setStatus("Copied") }
    catch { setStatus("Copy unavailable") }
  }}><span aria-live="polite">{status || label}</span></Button>
}

function render(tokens: Token[], inline = false): React.ReactNode {
  return tokens.map((token, key) => {
    const t = token as Tokens.Generic
    const children = () => render(t.tokens ?? [], true)
    switch (t.type) {
      case "space": return null
      case "heading": {
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
      case "blockquote": return <blockquote key={key} className="space-y-2 border-l-2 border-secondary pl-3">{render(t.tokens ?? [])}</blockquote>
      case "list": {
        const List = t.ordered ? "ol" : "ul"
        return <List key={key} start={t.ordered ? t.start : undefined} className={`space-y-1 pl-5 ${t.ordered ? "list-decimal" : "list-disc"}`}>
          {(t.items as Tokens.ListItem[]).map((item, index) => <li key={index}>{item.task && <span aria-label={item.checked ? "Completed" : "Incomplete"}>{item.checked ? "☑ " : "☐ "}</span>}{render(item.tokens)}</li>)}
        </List>
      }
      case "table": {
        const table = token as Tokens.Table
        return <table key={key} className="w-full table-fixed border-collapse text-sm">
          <thead><tr>{table.header.map((cell, index) => <th scope="col" key={index} className="border bg-muted p-2 text-left">{render(cell.tokens, true)}</th>)}</tr></thead>
          <tbody>{table.rows.map((row, index) => <tr key={index}>{row.map((cell, column) => <td key={column} className="border p-2 align-top">{render(cell.tokens, true)}</td>)}</tr>)}</tbody>
        </table>
      }
      case "code": return <div key={key} className="min-w-0 rounded-lg border bg-muted/50">
        <div className="flex items-center justify-between gap-2 px-3 text-xs text-muted-foreground"><span>{t.lang || "Code"}</span><Copy value={t.text} label="Copy code" /></div>
        <pre tabIndex={0} className="overflow-x-auto border-t p-3 font-mono text-sm leading-relaxed [overflow-wrap:normal]"><code>{t.text}</code></pre>
      </div>
      case "image": case "escape": return <span key={key}>{t.text}</span>
      case "text": return t.tokens?.length ? <span key={key}>{render(t.tokens, true)}</span>
        : inline ? t.text : <span key={key}>{t.text}</span>
      default: return <span key={key}>{t.raw}</span>
    }
  })
}

export const NotebookReply = memo(function NotebookReply({ content, streaming, partial }: {
  content: string; streaming: boolean; partial?: boolean
}) {
  const [collapsed, setCollapsed] = useState(false)
  const body = useMemo(() => render(marked.lexer(content)), [content])
  return <article className="min-w-0 space-y-2 rounded-xl border bg-card/40 px-4 py-3 sm:px-5">
    <h3 className="flex flex-wrap items-center gap-2 text-sm font-medium">Socra Tutor
      {streaming && <span className="text-xs font-normal text-secondary">Responding…</span>}
      {partial && <span className="text-xs font-normal text-muted-foreground">Partial response</span>}
    </h3>
    <div hidden={collapsed} className="min-w-0 space-y-3 text-[15px] leading-relaxed [overflow-wrap:anywhere]">{body}</div>
    {!streaming && <div className="flex flex-wrap items-center gap-1">
      <Copy value={content} label="Copy response" />
      {content.length > 1800 && <Button size="sm" variant="ghost" aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}>{collapsed ? "Expand response" : "Collapse response"}</Button>}
    </div>}
  </article>
})
