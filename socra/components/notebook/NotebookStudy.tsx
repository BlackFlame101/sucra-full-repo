"use client"

import Link from "next/link"
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ExerciseCard } from "@/components/chat/ExerciseCard"
import { ExerciseFeedbackCard } from "@/components/chat/ExerciseFeedbackCard"
import { TabsContent } from "@/components/ui/tabs"
import { NotebookReply } from "./NotebookReply"
import { useSocraChat } from "@/hooks/useSocraChat"
import { useUserSettings } from "@/hooks/useUserSettings"
import type { NotebookAction, PublicCorrection, PublicExercise } from "@/lib/socra-ws"
import type { Note } from "@/lib/notebook/notes"
import type { EditAnchor, EditPlacement, SelectionRequest } from "./NoteEditor"
import type { NoteWorkspaceHandle } from "./NoteWorkspace"
import { EditReview } from "./EditReview"

type Thread = { sessionId: string; courseId: string; language: "en" | "fr" }
type Card = { question: string; answer: string }
type Props = { note: Note; workspace: RefObject<NoteWorkspaceHandle | null>; tab: string;
  selectionRequest?: SelectionRequest; onSelectionHandled: () => void;
  onReview: (id: string, date: string | null) => void; onApplied: () => void }
const edits = {
  improve: "Improve writing", expand: "Expand explanation", simplify: "Simplify selected text",
  example: "Add examples", summarize: "Summarize", correct: "Correct conceptual mistakes",
} as const

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || "The request could not be completed.")
  return data
}

export function NotebookStudy(props: Props) {
  const [thread, setThread] = useState<Thread>()
  const [opening, setOpening] = useState(false)
  const [error, setError] = useState("")
  const [openingFailed, setOpeningFailed] = useState(false)
  const openingRef = useRef(false)
  const noteId = props.note.id
  const open = useCallback(async () => {
    if (openingRef.current) return
    openingRef.current = true
    setOpening(true)
    setError("")
    try {
      setThread(await request<Thread>("/api/notebook/" + noteId + "/study", { method: "POST" }))
    } catch (cause) {
      setError(String(cause instanceof Error ? cause.message : cause))
      setOpeningFailed(true)
    }
    finally { openingRef.current = false; setOpening(false) }
  }, [noteId])
  useEffect(() => {
    if ((!props.selectionRequest && props.tab !== "ask") || thread) return
    const timer = setTimeout(() => void open(), 0)
    return () => clearTimeout(timer)
  }, [props.selectionRequest, props.tab, thread, open])
  return <>
    {thread ? <NotebookThread {...props} thread={thread} /> : props.tab !== "sources" && <TabsContent value={props.tab} className="min-h-0 overflow-y-auto p-4">
      <Button size="sm" disabled={opening} onClick={() => void open()}>{opening ? "Opening." : "Open note inquiry"}</Button>
      {error && !props.selectionRequest && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {props.tab === "tools" && <ReviewSchedule note={props.note} onReview={props.onReview} />}
    </TabsContent>}
    {props.selectionRequest && !thread && openingFailed && <EditReview anchor={props.selectionRequest.anchor}
      suggestion="" busy={opening} status={error} onApply={() => undefined} onRegenerate={() => void open()}
      onDiscard={props.onSelectionHandled} onCloseFocus={() => document.querySelector<HTMLElement>(".notebook-editor")?.focus()} />}
  </>
}

function NotebookThread({ note, workspace, thread, tab, onApplied, selectionRequest, onSelectionHandled, onReview }: Props & { thread: Thread }) {
  const { getActiveConfig } = useUserSettings()
  const base = "/api/notebook/" + note.id + "/study"
  const [input, setInput] = useState("")
  const [questionAnchor, setQuestionAnchor] = useState<EditAnchor | null>(null)
  const questionInput = useRef<HTMLInputElement>(null)
  const transcript = useRef<HTMLDivElement>(null)
  const transcriptBody = useRef<HTMLDivElement>(null)
  const following = useRef(true)
  const savedTop = useRef(0)
  const [jumpVisible, setJumpVisible] = useState(false)
  const alignTranscript = useCallback(() => {
    const node = transcript.current
    if (!node?.clientHeight) return
    if (following.current) node.scrollTop = node.scrollHeight
    else node.scrollTop = savedTop.current
  }, [])
  const handledSelection = useRef<SelectionRequest | null>(null)
  const [pending, setPending] = useState(false)
  const busyRef = useRef(false)
  const discardPending = useRef(false)
  const [error, setError] = useState("")
  const [history, setHistory] = useState<"loading" | "loaded" | "error">("loading")
  const [historyRevision, setHistoryRevision] = useState(0)
  const [exercise, setExercise] = useState<PublicExercise>()
  const [correction, setCorrection] = useState<PublicCorrection>()
  const [proposal, setProposal] = useState<{ anchor: EditAnchor | null; priorId?: string; action: NotebookAction; prompt: string }>()
  const reviewTrigger = useRef<HTMLElement | null>(null)
  const [cards, setCards] = useState<Card[]>([])
  const [stale, setStale] = useState(false)
  const [card, setCard] = useState(0)
  const [revealed, setRevealed] = useState(false)
  const chat = useSocraChat({ ...thread, llmConfig: getActiveConfig(), recoverInterrupted: history === "loaded",
    onExercise: setExercise, onCorrection: setCorrection })
  const { sendMessage, setMessages } = chat
  const idle = chat.status === "ready" || chat.status === "error"
  const busy = pending || !idle || history !== "loaded"
  const lastAnswer = chat.messages.findLast((entry) => entry.role === "assistant")
  const proposalText = proposal && idle && chat.status === "ready" &&
    (lastAnswer?.metadata as { persisted?: boolean } | undefined)?.persisted && lastAnswer?.id !== proposal.priorId
    ? lastAnswer?.parts.flatMap((part) => part.type === "text" ? [part.text] : []).join("\n") : ""

  useLayoutEffect(() => {
    if (tab === "ask") alignTranscript()
  }, [alignTranscript, tab, chat.messages])
  useEffect(() => {
    const node = transcript.current
    const body = transcriptBody.current
    if (!node || !body) return
    const observer = new ResizeObserver(alignTranscript)
    observer.observe(node)
    observer.observe(body)
    return () => observer.disconnect()
  }, [alignTranscript])

  useEffect(() => {
    const controller = new AbortController()
    request<Array<{ id: string; role: string; content: string;
      metadata?: { exercise?: PublicExercise; correction?: PublicCorrection; exercise_id?: string } }>>(
      "/api/sessions/" + thread.sessionId + "/messages", { signal: controller.signal })
      .then((rows) => {
        if (controller.signal.aborted) return
        setMessages(rows.flatMap((row) => row.role === "user" || row.role === "assistant" ? [{
          id: row.id, role: row.role, parts: [{ type: "text", text: row.content }], metadata: { ...row.metadata, persisted: true },
        }] : []))
        const latest = rows.findLastIndex((row) => row.metadata?.exercise)
        const activeExercise = rows[latest]?.metadata?.exercise
        setExercise(activeExercise)
        setCorrection(activeExercise
          ? rows.findLast((row) => row.metadata?.exercise_id === activeExercise.id && row.metadata.correction)?.metadata?.correction
          : undefined)
        setHistory("loaded")
      }).catch(() => { if (!controller.signal.aborted) setHistory("error") })
    return () => controller.abort()
  }, [thread.sessionId, setMessages, historyRevision])

  useEffect(() => {
    if (tab !== "tools" || !idle) return
    const controller = new AbortController()
    request<{ cards: Card[]; stale: boolean }>(base, { signal: controller.signal }).then((data) => {
      if (controller.signal.aborted) return
      setCards(data.cards)
      setStale(data.stale)
      setCard(0)
      setRevealed(false)
    }).catch(() => { if (!controller.signal.aborted) setError("Could not load saved flashcards.") })
    return () => controller.abort()
  }, [base, idle, tab, note.version])

  const run = useCallback(async (action: NotebookAction, text: string, edit = false, captured?: EditAnchor | null) => {
    if (busy || busyRef.current || !text.trim()) return
    busyRef.current = true
    discardPending.current = false
    const anchor = captured === undefined ? workspace.current?.selection() ?? null : captured
    if (edit && !proposal) reviewTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setPending(true)
    setError("")
    setProposal(edit ? { anchor, priorId: lastAnswer?.id, action, prompt: text } : undefined)
    try {
      if (!await workspace.current?.save()) throw new Error("Save or resolve the current draft first.")
      if (discardPending.current) return
      if (action === "quiz") { setExercise(undefined); setCorrection(undefined) }
      const selection = action !== "quiz" && action !== "flashcards" ? anchor?.text.trim() : undefined
      sendMessage({ text: text.trim(), mode: action === "quiz" ? "exercise" : "explain",
        notebook: { id: note.id, action, ...(selection ? { selection: selection.slice(0, 2000) } : {}) } })
      setInput("")
      setQuestionAnchor(null)
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not start the request.") }
    finally { busyRef.current = false; setPending(false) }
  }, [busy, workspace, proposal, lastAnswer?.id, sendMessage, note.id])

  useEffect(() => {
    if (!selectionRequest || busy || handledSelection.current === selectionRequest) return
    const timer = setTimeout(() => {
      handledSelection.current = selectionRequest
      onSelectionHandled()
      const { anchor, action } = selectionRequest
      if (action === "ask") {
        setQuestionAnchor(anchor)
        questionInput.current?.focus()
      } else if (action === "explain") void run("ask", "Explain this selection.", false, anchor)
      else void run(action, edits[action], true, anchor)
    }, 0)
    return () => clearTimeout(timer)
  }, [selectionRequest, busy, onSelectionHandled, run])

  function apply(placement: EditPlacement) {
    if (!proposalText || !proposal) return
    if (!workspace.current?.apply(proposalText, placement, proposal.anchor)) {
      setError("The note changed after this request. Return to the editor and select the passage again, or add this suggestion to the end.")
      return
    }
    setProposal(undefined)
    setError("")
    onApplied()
  }

  const status = chat.error?.message || error || (pending ? "Saving note…" : history === "loading" ? "Loading inquiry…" :
    history === "error" ? "Inquiry history unavailable." : !idle ? chat.progress || "Waiting for Socra…" : "")
  const feedback = <>
    {status && <p role={chat.error || error || history === "error" ? "alert" : "status"} className="text-xs text-muted-foreground">{status}</p>}
    {history === "error" && <Button size="sm" variant="outline" onClick={() => {
      setHistory("loading")
      setHistoryRevision((value) => value + 1)
    }}>Retry loading inquiry</Button>}
    {chat.canRegenerate && (chat.status === "error" || chat.interrupted) &&
      <Button size="sm" variant="outline" onClick={chat.regenerate}>{chat.interrupted ? "Resume last request" : "Retry response"}</Button>}
  </>
  const inquiryLink = <Link className="text-xs text-secondary hover:underline"
    href={"/dashboard/course/" + thread.courseId + "/inquiry/" + thread.sessionId + "?note=" + note.id}
    onClick={async (event) => {
      event.preventDefault()
      const href = event.currentTarget.href
      if (await workspace.current?.save()) location.assign(href)
      else setError("Save or resolve the current draft first.")
    }}>Continue learning from this note</Link>

  return <>
    <TabsContent value="ask" forceMount className="flex min-h-0 flex-col data-[state=inactive]:hidden">
      <div className="relative min-h-0 flex-1">
        <div ref={transcript} tabIndex={0} aria-label="Note inquiry messages"
          className="absolute inset-0 min-w-0 overflow-y-auto overscroll-contain [overflow-anchor:none]"
          onScroll={(event) => {
            const node = event.currentTarget
            if (!node.clientHeight) return
            following.current = node.scrollHeight - node.scrollTop - node.clientHeight < 100
            savedTop.current = node.scrollTop
            setJumpVisible(!following.current)
          }}>
          <div ref={transcriptBody} className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
            {!chat.messages.length && history === "loaded" && <div className="space-y-3">
              <p className="font-serif text-xl">What would you like to understand?</p>
              <div className="flex flex-wrap gap-2">
                {(["Explain this", "Explain more simply", "Give an example", "Find related course material"] as const).map((prompt, index) =>
                  <Button key={prompt} variant="outline" size="sm" disabled={busy}
                    onClick={() => void run(index === 3 ? "related" : "ask", prompt)}>{prompt}</Button>)}
              </div>
            </div>}
            {chat.messages.map((message) => {
              const content = message.parts.flatMap((part) => part.type === "text" ? [part.text] : []).join("\n")
              const metadata = message.metadata as { notebook_action?: string; request_id?: string; partial?: boolean } | undefined
              const isEdit = metadata?.notebook_action && Object.hasOwn(edits, metadata.notebook_action)
              const key = metadata?.request_id ? metadata.request_id + ":" + message.role : message.id
              if (isEdit && message.role === "assistant") return <p key={key} className="rounded-lg border px-4 py-3 text-sm text-muted-foreground">
                {content && !metadata?.partial && (idle || message.id !== lastAnswer?.id)
                  ? "Socra generated an edit suggestion." : "Edit suggestion requested."}
              </p>
              if (!content) return null
              return message.role === "assistant"
                ? <NotebookReply key={key} content={content} streaming={!idle && message.id === lastAnswer?.id} partial={metadata?.partial} />
                : <p key={key} className="ml-auto w-fit max-w-[90%] whitespace-pre-wrap rounded-xl bg-secondary/10 px-4 py-2 text-sm [overflow-wrap:anywhere]">{content}</p>
            })}
          </div>
        </div>
        {jumpVisible && <Button type="button" size="sm" variant="outline" className="absolute right-5 bottom-3 bg-card shadow-md"
          onClick={() => { following.current = true; setJumpVisible(false); alignTranscript() }}>↓ Jump to latest</Button>}
      </div>
      <div className="shrink-0 border-t bg-card px-3 py-2 sm:px-4">
        <div className="mx-auto max-w-4xl space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <span className="max-w-full truncate text-xs text-muted-foreground" title={note.title}>{note.title}</span>
            {inquiryLink}
          </div>
          {feedback}
          {questionAnchor && <Button size="sm" variant="ghost" onClick={() => setQuestionAnchor(null)}>Clear attached selection</Button>}
          <form className="flex flex-wrap items-center gap-2" onSubmit={(event) => { event.preventDefault(); void run("ask", input, false, questionAnchor ?? undefined) }}>
            <Input ref={questionInput} className="min-w-28 flex-1" value={input} maxLength={2000} onChange={(event) => setInput(event.target.value)}
              aria-label="Ask Socra about this note" placeholder="Ask about this note…" />
            {!idle ? <Button type="button" size="sm" variant="outline" onClick={chat.stop}>Stop generation</Button>
              : <Button type="submit" size="sm" disabled={busy || !input.trim()}>Send</Button>}
          </form>
        </div>
      </div>
    </TabsContent>
    <TabsContent value="tools" className="min-h-0 space-y-3 overflow-y-auto overscroll-contain p-3">
      {feedback}
      {!idle && <Button size="sm" variant="ghost" onClick={chat.stop}>Stop generation</Button>}

      <div className="flex flex-wrap gap-1">
        <Button size="sm" variant="outline" disabled={busy} onClick={() => void run("flashcards", "Generate flashcards from this note.")}>Generate flashcards</Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => void run("quiz", "Generate a short-answer practice question based on this note.")}>Quiz me</Button>
      </div>
      {stale && <p className="text-xs text-muted-foreground">These cards were generated before the latest note edit.</p>}
      {cards[card] && <section className="space-y-2 rounded-lg border p-3 text-sm" aria-label="Flashcard review">
        <p>{cards[card].question}</p>
        {revealed && <p className="text-muted-foreground">{cards[card].answer}</p>}
        <div className="flex flex-wrap gap-1">
          <Button variant="outline" size="sm" onClick={() => setRevealed(!revealed)}>{revealed ? "Hide answer" : "Show answer"}</Button>
          <Button variant="ghost" size="sm" onClick={() => { setCard((card + 1) % cards.length); setRevealed(false) }}>Next card</Button>
        </div>
        <p className="text-xs text-muted-foreground">{card + 1} of {cards.length}</p>
      </section>}
      {exercise && <ExerciseCard exercise={exercise} disabled={busy} submissionLocked={Boolean(correction)}
        onSubmitAttempt={(answer, hintsUsed) => chat.submitAttempt({ exerciseId: exercise.id, answer, hintsUsed })}
        onNextExercise={() => void run("quiz", "Generate another short-answer practice question based on this note.")} />}
      {correction && <ExerciseFeedbackCard correction={correction} solution={null} readOnly />}
      <div className="flex flex-wrap gap-1" role="group" aria-label="Suggest an edit">
        {Object.entries(edits).map(([action, label]) => <Button key={action} size="sm" variant="outline" disabled={busy}
          onClick={() => void run(action as NotebookAction, label, true)}>{label}</Button>)}
      </div>
      <ReviewSchedule note={note} onReview={onReview} />
    </TabsContent>
  {proposal && <EditReview anchor={proposal.anchor} suggestion={proposalText || ""} busy={busy}
    status={error || chat.error?.message || (busy ? chat.progress || "Preparing suggestion." : "")}
    onApply={apply} onRegenerate={() => void run(proposal.action, proposal.prompt, true, proposal.anchor)}
    onDiscard={() => { discardPending.current = true; if (!idle) chat.stop(); setProposal(undefined); setError("") }}
    onCloseFocus={() => { if (!document.activeElement?.closest(".notebook-editor")) reviewTrigger.current?.focus() }} />}
  </>
}

function ReviewSchedule({ note, onReview }: Pick<Props, "note" | "onReview">) {
  const [date, setDate] = useState(note.review_due ?? "")
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState("")
  async function update(value: string | null) {
    setBusy(true)
    try {
      const data = await request<{ review_due: string | null }>("/api/notebook/" + note.id + "/study", {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ review_due: value }),
      })
      onReview(note.id, data.review_due)
      setDate(data.review_due ?? "")
      setStatus(value ? "Review date saved." : "Review completed.")
    } catch (cause) { setStatus(cause instanceof Error ? cause.message : "Could not save your review date.") }
    finally { setBusy(false) }
  }
  return <form className="mt-3 space-y-2 rounded-lg border p-2" onSubmit={(event) => { event.preventDefault(); void update(date) }}>
    <label className="block text-sm" htmlFor="note-review-date">Revisit later</label>
    <Input id="note-review-date" type="date" value={date} required onChange={(event) => setDate(event.target.value)} />
    <div className="flex flex-wrap gap-1">
      <Button size="sm" type="submit" disabled={busy || !date}>Schedule review</Button>
      {note.review_due && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void update(null)}>Mark reviewed</Button>}
    </div>
    {status && <p role="status" className="text-xs text-muted-foreground">{status}</p>}
  </form>
}
