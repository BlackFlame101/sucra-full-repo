const empty = {
  definition: "", intuition: "", sections: [], course_example: "", common_pitfalls: [], check_question: "", citations: [],
}
const source = (id, filename, page_number, excerpt) => ({
  document_id: `00000000-0000-0000-0000-${id.padStart(12, "0")}`, filename, page_number, excerpt,
})
const section = (heading, content = "", citations = []) => ({ heading, content, citations })
const lab = (page, excerpt) => source("1", "Fraud detection lab.pdf", page, excerpt)
const algebra = (page, excerpt) => source("2", "Algebra chapter.pdf", page, excerpt)
const grammar = (page, excerpt) => source("3", "French grammar.pdf", page, excerpt)
const paper = (page, excerpt) => source("5", "Remote work study.pdf", page, excerpt)

export const python = "def load_rows(path):\r\n    with open(path, encoding=\"utf-8\") as data:\r\n        return data.read().splitlines()  "

export const explanationFixtures = {
  standard: {
    ...empty, presentation: "standard",
    definition: "# Why normalize features before kNN?\n\nScaling makes distances less sensitive to the units used to record a feature.",
    intuition: "kNN compares observations by distance. When one feature has a much wider numerical range, differences in that feature can outweigh differences in the others.",
    sections: [
      section("What this means in your data", "Compare an amount field measured in currency with a binary indicator. Their raw differences are measured on very different scales."),
      section("Try it in the workflow", "1. Open **Preprocess**.\n2. Add **Normalize Features**.\n3. Connect the preprocessor to kNN and re-run the evaluation."),
      section("Expected results", "Compare the two runs using the same held-out split.", [lab(7, "Compare performance after scaling.")]),
      section("What changes", "| Metric | Value |\n| --- | --- |\n| Example F1 before scaling | 0.478 |\n| Example F1 after scaling | 0.780 |",
        [lab(7, "Fixture reference values for the two runs.")]),
    ],
    common_pitfalls: ["Scaling the inputs and changing the split at the same time makes the comparison ambiguous."],
    check_question: "When would scaling have little effect on the nearest neighbours?",
  },
  brief: {
    ...empty, presentation: "brief",
    sections: [section("Summary", "The exercise compares the same classification workflow in two tools using held-out data.\n\n### Key points\n\n- Use the same target variable.\n- Use the same split.\n- Compare the same metric.\n\n### Tool comparison\n\n| Step | Orange | KNIME |\n| --- | --- | --- |\n| Read the data | File | CSV Reader |")],
    citations: [lab(7, "Evaluate the workflow."), lab(2, "Load the original dataset.")],
    common_pitfalls: ["Changing the split between runs makes the scores harder to compare."],
    check_question: "Why keep the split fixed?",
  },
  sentence: {
    ...empty, presentation: "brief",
    sections: [section("Summary", "The exercise compares classifiers on the same held-out data.")],
    citations: [lab(7, "Evaluate the workflow.")],
  },
  guide: {
    ...empty,
    definition: "# Fraud detection with Orange and KNIME\n\nBuild the same workflow in both tools, then compare what each reports on the held-out data.",
    sections: [
      section("Part 1 · Orange"),
      section("Step 1 · Set up Orange", [
        "Install Orange from a terminal, then launch it.",
        "### Before you begin\n- [x] Open the Orange workspace.\n- [ ] Find the widget toolbox.",
        "~~~powershell\npython -m pip install orange3\npython -m Orange.canvas\n~~~",
        "### Expected result\nThe canvas opens with the widget toolbox visible.",
        "### Troubleshooting\nIf the Python install fails, use the desktop installer described in the appendix.",
      ].join("\n\n"), [lab(2, "Open the canvas and locate the widget toolbox.")]),
      section("Step 2 · Inspect the transactions", [
        "1. Drop a **File** widget onto the canvas.\n2. Choose the transactions dataset and set the target.",
        "- [ ] Confirm the target is categorical.\n- [ ] Inspect the distribution.",
        "### Screenshot checkpoint\nCapture the distribution after setting the target.",
      ].join("\n\n"), [lab(4, "Capture the class distribution after setting the target.")]),
      section("Part 2 · KNIME"),
      section("Step 3 · Rebuild the workflow", "Add a CSV Reader and connect it to the partitioning node. Keep the same target as in the Orange workflow.", [lab(7, "Use the same target for the second workflow.")]),
      section("Step 4 · Optional script", `~~~python\r\n${python}\r\n~~~`),
      section("Deliverables", "Submit both workflow exports and a comparison of the held-out results.\n\n| Tool | Held-out result |\n| --- | --- |\n| Orange | |\n| KNIME | |", [lab(10, "Submit the two workflows and a written comparison.")]),
      section("Coverage check", "Insufficiently covered requirements. Ask to continue with these items (2): screenshot:2 (p. 7), appendix:A (p. 11)."),
    ],
    citations: [lab(2, "Open the canvas and locate the widget toolbox."), lab(10, "Submit the two workflows and a written comparison.")],
  },
  math: {
    ...empty,
    definition: "# Deriving the quadratic formula\n\nComplete the square in a sequence of reversible steps.",
    sections: [
      section("Formula", String.raw`For $a \ne 0$, the real solutions when $b^2-4ac\ge 0$ are

$$x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}$$`, [algebra(4, "The discriminant determines whether the roots are real.")]),
      section("Derivation", String.raw`| Equation | Reason |
| --- | --- |
| $x^2+\frac{b}{a}x=-\frac{c}{a}$ | Divide by the leading coefficient and move the constant. |
| $\left(x+\frac{b}{2a}\right)^2=\frac{b^2-4ac}{4a^2}$ | Add the square of half the linear coefficient. |
| $x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}$ | Take both square roots and isolate $x$. |`, [algebra(5, "Complete the square, take both roots, then isolate the unknown.")]),
      section("Worked example", String.raw`For $2x^2-4x-6=0$, divide by $2$ and factor to obtain $(x-3)(x+1)=0$.

### Verification

$$2(3)^2-4(3)-6=18-12-6=0\quad\text{and}\quad 2(-1)^2-4(-1)-6=2+4-6=0$$`),
    ],
    citations: [algebra(4, "The discriminant determines whether the roots are real.")],
  },
  language: {
    ...empty,
    definition: "# Passé composé or imparfait?\n\nUse the imparfait for a scene or habit and the passé composé for an event.",
    sections: [
      section("Rules", "### Imparfait\nDescribe a setting or an ongoing action.\n\n### Passé composé\nReport a completed event or an interruption.", [grammar(3, "The imparfait can supply background for an event in the passé composé.")]),
      section("Comparison", "| Correct in this context | Incorrect in this context |\n| --- | --- |\n| Je lisais quand il est entré. | J’ai lu quand il est entré. |", [grammar(4, "The ongoing reading is the background for his entrance.")]),
      section("Vocabulary", "| Habit | Event |\n| --- | --- |\n| chaque été | soudain |\n| souvent | hier |"),
      section("Practice", "### Question 1\nQuand j’étais petit, je ___ (jouer) chaque jour.\n\n### Answer 1\n*Jouais*. The time phrase signals a habit.\n\n### Question 2\nLe téléphone ___ (sonner) soudain.\n\n**Answer:** *A sonné*. The sentence describes a sudden event."),
      section("Common mistake", "Check whether the sentence presents the action as ongoing or complete before you conjugate."),
    ],
    citations: [grammar(3, "The imparfait can supply background for an event in the passé composé.")],
  },
  compact: {
    ...empty,
    definition: "# What is overfitting?\n\nOverfitting occurs when a model learns noise in the training data and performs worse on unseen examples.",
    sections: [
      section("Example", "A very deep decision tree can memorize details unique to the training set."),
      section("Key takeaway", "Compare performance on training and validation data."),
    ],
    citations: [source("4", "Machine learning basics.pdf", 8, "A validation set reveals performance on unseen examples.")],
  },
  research: {
    ...empty,
    definition: "# Remote work and employee productivity\n\nA short reading of the study question, reported evidence and limits.",
    sections: [
      section("Research question", "How does measured productivity differ between remote and office-based workers?", [paper(2, "The study compares measured productivity by location.")]),
      section("Methodology", "The researchers observed two teams for six weeks and compared weekly task completion.", [paper(3, "Two teams were observed over six weeks.")]),
      section("Key findings", "The remote team completed more tasks per week in the sample.", [paper(4, "Weekly averages were 22 tasks for the remote team and 20 for the office team.")]),
      section("Supporting evidence", "| Outcome | Remote team | Office-based team |\n| --- | --- | --- |\n| Tasks per week | 22 | 20 |", [paper(4, "Weekly averages were 22 tasks for the remote team and 20 for the office team.")]),
      section("Interpretation", "The difference describes these teams and the measured outcome. Work complexity may vary."),
      section("Limitations", "The teams were observed within one company over a short period. Employees were not randomly assigned to locations."),
    ],
    citations: [paper(2, "The study compares measured productivity by location."), paper(4, "Weekly averages were 22 tasks for the remote team and 20 for the office team.")],
  },
}

const guide = explanationFixtures.guide
explanationFixtures.exhaustive = {
  ...guide, presentation: "walkthrough",
  sections: [
    { ...guide.sections[1], heading: "Part 1: Setup — Prepare the workspace" },
    section("Part 1: Setup — Record the software versions", "1. Open the application's About dialog.\n2. Record its version in the report."),
    { ...guide.sections[2], heading: "Part 2: Orange — Inspect the transactions" },
    section("Part 2: Orange — Save the workflow", "- [ ] Save a copy of the workflow after checking the target."),
    { ...guide.sections[4], heading: "Part 3: KNIME — Rebuild the workflow" },
    { ...guide.sections[5], heading: "Part 3: KNIME — Optional script" },
    section("Mandatory analysis questions", [
      "### Question 1\nInspect the held-out result and record which metric you used.",
      "### Question 2\nCompare the same metric across runs and describe any limitations.",
    ].join("\n\n")),
    { ...guide.sections[6], content: "Complete the template with your measured results.\n\n| Modèle évalué | Après amélioration |\n| --- | --- |\n| Orange | |\n| KNIME | |" },
    guide.sections.at(-1),
  ],
}

// Synthetic model outputs in the Phase 7 serializer shape. Values are test inputs only.
export function phase7Fixture(scenario = "course") {
  const titles = {
    concept: "Fixture concept", derivation: "Fixture derivation", worked_calculation: "Fixture calculation",
    comparison: "Fixture comparison", figure_walkthrough: "Fixture figure", rule_examples: "Fixture rule",
    exercise: "Fixture question", lab_step: "Fixture KNIME step", research_finding: "Fixture finding",
    transition: "Part II", front_matter: "Contents", summary: "Recap",
  }
  const kinds = scenario === "course" ? Object.keys(titles).filter((kind) => kind !== "exercise" && kind !== "lab_step")
    : scenario === "exercises" ? ["exercise", "exercise", "exercise"] : ["lab_step", "lab_step", "lab_step"]
  const statuses = ["partial", "not_generated"]
  const request_id = "request-" + scenario
  const document_id = "synthetic-pdf-" + scenario
  const source_hash = "synthetic-index"
  const generation = 4
  const rows = kinds.map((kind, i) => {
    const logical_id = scenario + "-" + (i + 1)
    const content_version = "content-" + logical_id
    const skipped = scenario === "exercises" && i === 2
    const nonTeaching = ["transition", "front_matter", "summary"].includes(kind)
    const status = skipped || nonTeaching ? "skipped" : statuses[i] ?? "explained"
    const pages = [i + 1, i + 1]
    const title = titles[kind]
    const verification = status === "skipped" ? "not_applicable" : i === 0 ? "review_failed"
      : i === 1 ? "unreviewed" : "reviewed"
    const unverifiable_source = i === 0 ? [{ page: i + 1, status: "unverifiable_source", reason: "preparation_pending" }] : []
    const missing_item_ids = i < 2 ? ["requirement-" + logical_id] : []
    const scope_reason = skipped ? "exercise_excluded" : nonTeaching ? "non_teaching" : "requested"
    return { kind, label: scenario === "course" ? "II." + (i + 1) : String(i + 1),
      progress: { logical_id, title, content_version, status, pages, missing_item_ids,
        verification, unverifiable_source, scope_reason } }
  })
  const progress = rows.map((row) => row.progress)
  const sectionRows = rows.filter(({ progress }) => progress.scope_reason !== "non_teaching")
    .map(({ kind, label, progress }) => ({
      id: progress.logical_id, title: progress.title, content_version: progress.content_version,
      label, kind, start: progress.pages[0], end: progress.pages[1],
      status: { explained: "covered", partial: "partial" }[progress.status] ?? "not_yet_generated",
    }))
  const units = rows.filter(({ progress }) => progress.status !== "skipped").map(({ kind, progress }) => {
    const { logical_id, title, content_version, status, verification, missing_item_ids, unverifiable_source, pages } = progress
    return {
      logical_id, title, content_version, coverage: status, verification, confidence: status === "explained" ? "high" : "low",
      missing_item_ids, unverifiable_source, verified_facts: [], findings: [],
      interruptions: status === "not_generated" ? ["call_budget"] : [],
      sources: status === "not_generated" ? [] : [{ page: pages[0], start: 0, end: 22, quote: "Synthetic source text." }],
      blocks: status === "not_generated" ? [] : [{ kind: { exercise: "final_answer", lab_step: "command_or_ui" }[kind] ?? "explanation",
        block_id: "block-" + logical_id, text: "Synthetic source text.", provenance: "course", source_indexes: [1] },
      { kind: "intuition", block_id: "example-" + logical_id, text: "A hypothetical example.",
        provenance: "supplementary", hypothetical: true, source_indexes: [] }],
    }
  })
  const change = { block_id: units[0].blocks[0].block_id, old_quote: "Earlier fixture text.",
    new_quote: units[0].blocks[0].text, reason: "review_repair", severity: "high" }
  const versions = units.map((output, i) => ({ request_id, stage: "ready", output,
    change_log: i === 0 ? [change] : [], document_id, generation, source_hash, identity: sectionRows[i] }))
  const next_actions = [
    { action: "continue_learning", logical_id: progress[1].logical_id, request_id: "continue-" + scenario, attempt: 1 },
    { action: "deepen_unit", logical_id: progress[0].logical_id, request_id: "deepen-" + scenario, attempt: 2 },
  ]
  const count = (key) => progress.reduce((counts, row) => ({ ...counts, [row[key]]: (counts[row[key]] ?? 0) + 1 }), {})
  const ledger = { coverage_counts: count("status"), verification_counts: count("verification"),
    remaining: [progress[1]], partial: [progress[0]], skipped_optional_items: {}, low_fidelity_pages: [1],
    corrections: [{ logical_id: progress[0].logical_id, ...change }], next_actions }
  const card = { ...empty, schema_version: 2, units, versions, language: "French", presentation: "full_course",
    sections: [section(units[0].title, units[0].blocks[0].text)],
    course_progress: { request_id, document_id, index_generation: generation, source_hash, sections: sectionRows,
      part: 2, total_parts: 3, next_request_id: next_actions[0].request_id, inventory_uncertain: false,
      learning_plan: { scope: Object.fromEntries(progress.map((row) =>
        [row.logical_id, { in_scope: row.status !== "skipped", reason: row.scope_reason }])),
      order: progress.filter((row) => row.status !== "skipped").map((row) => row.logical_id),
      assumptions: [], depth: "exhaustive", level: "standard", required_items: {}, unverifiable_source: {},
      remaining: ledger.remaining, next_actions, facts_ledger: [] } },
    learning_state: { progress, facts: { verified_facts: [] }, next_actions }, coverage_ledger: ledger }
  const draft = { ...versions[0], stage: "draft", change_log: [], output: { ...units[0],
    verification: "unreviewed", blocks: [{ ...units[0].blocks[0], text: change.old_quote }] } }
  const snapshot = { document_id, generation, source_hash, request_id, revision: 3, versions: [draft, ...versions], calls: [] }
  return { card, draft, snapshot, change }
}

const instructionalBlocks = {
  concept: [
    ["takeaway", "Fit preprocessing on the training split."],
    ["explanation", "Leakage occurs when evaluation data influences the fitted model."],
    ["source_example", "| Split | Rows |\n| --- | ---: |\n| Training | 80 |\n| Evaluation | 20 |", "course"],
    ["intuition", "Imagine reading the answers before a quiz.", "supplementary", { hypothetical: true }],
    ["check_question", "Which split should fit the scaler?"],
  ],
  derivation: [
    ["given", "$P$ is precision and $R$ is recall."],
    ["ordered_steps", "- Write the reciprocal sum.\n- Invert the arithmetic mean."],
    ["result", "$$F_1 = \\frac{2PR}{P+R}$$", "derived"],
    ["interpretation", "A low recall limits the harmonic mean."],
  ],
  worked_calculation: [
    ["given_values", "| Label | Value |\n| --- | ---: |\n| True positives | 9 |\n| Positives | 12 |"],
    ["formula", "~~~latex\nR = \\frac{TP}{P}\n~~~", "derived"],
    ["substitution", "$R = 9/12$", "derived"],
    ["calculation", "Divide 9 by 12.", "derived"],
    ["result", "$R = 0{,}75$", "derived"],
    ["verification", "The resulting proportion is within the valid interval.", "derived"],
  ],
  comparison: [
    ["criteria", "Compare the methods by scope and assumptions."],
    ["table", "| Criterion | Method A | Method B | Method C |\n| --- | --- | --- | --- |\n| Scope | Local | Global | Both |"],
    ["interpretation", "Method B summarizes overall behavior."],
    ["trade_off", "The local explanation may be easier to inspect for a single case."],
  ],
  figure_walkthrough: [
    ["what_it_shows", "The chart compares two approaches."],
    ["how_to_read", "1. Find the baseline.\n2. Read the value from the vertical axis."],
    ["specific_reading", "The second bar appears close to 0.5.", "unverified", { approximate: true }],
    ["takeaway", "Use the printed table to confirm exact values."],
  ],
  rule_examples: [
    ["rule", "Apply the rule when the condition holds."],
    ["sourced_examples", "**Source example.** The condition holds here.", "course"],
    ["sourced_examples", "**Additional example.** Imagine the same condition in another sentence.", "supplementary", { hypothetical: true }],
    ["interpretation", "The condition is the deciding factor."],
    ["common_error", "Check the exception before applying the rule."],
  ],
  exercise: [
    ["problem", "What fraction of 12 cases were detected if 9 were found?"],
    ["method", "Divide the number found by the total."],
    ["working", "1. Substitute $9$ and $12$.\n2. Reduce the fraction.", "derived"],
    ["final_answer", "$3/4$", "derived"],
    ["verification", "Multiplying $3/4$ by $12$ gives $9$.", "derived"],
  ],
  lab_step: [
    ["action", "Open the workflow editor."],
    ["command_or_ui", "1. Add a CSV Reader.\n2. Set the input file."],
    ["code", "~~~powershell\r\nGet-Content -LiteralPath './example.csv'\r\n~~~"],
    ["expected_result", "The preview shows the header and first rows."],
    ["checkpoint", "Capture the node output and its row count."],
    ["troubleshooting", "If columns are merged, confirm the separator."],
  ],
  research_finding: [
    ["evidence", "| Group | Error | Sample size |\n| --- | --- | --- |\n| A | 9.4% | 120 |\n| B | 8.2% | 120 |", "course"],
    ["interpretation", "The observed gap is 1.2 percentage points.", "derived"],
    ["limitations", "The sample does not establish a causal effect."],
    ["figure", "See the accompanying figure."],
  ],
}

export function instructionalFixture(kind) {
  const scenario = kind === "lab_step" ? "lab" : kind === "exercise" ? "exercises" : "course"
  const { card } = phase7Fixture(scenario)
  const identity = card.course_progress.sections.find((section) => section.kind === kind)
  const template = card.units.find((unit) => unit.logical_id === identity.id)
  const gap = kind === "figure_walkthrough"
  const source = { page: 12, start: 5, end: 23, quote: "Synthetic evidence." }
  const output = { ...template, blocks: instructionalBlocks[kind].map(([type, text, provenance = "course", extra], i) => ({
    block_id: "instruction-" + (i + 1), kind: type, text, provenance,
    source_indexes: provenance === "course" || provenance === "derived" ? [1] : [], ...extra,
  })), sources: [source], coverage: gap ? "partial" : "explained", verification: gap ? "review_failed" : "reviewed",
    missing_item_ids: gap ? ["figure-value"] : [],
    unverifiable_source: gap ? [{ page: 12, status: "unverifiable_source", reason: "preparation_pending" }] : [] }
  const version = { ...card.versions.find((row) => row.output.logical_id === identity.id), output, identity, change_log: [] }
  const progress = { ...card.learning_state.progress.find((row) => row.logical_id === identity.id),
    status: output.coverage, verification: output.verification, missing_item_ids: output.missing_item_ids,
    unverifiable_source: output.unverifiable_source }
  return { ...card, units: [output], versions: [version],
    learning_state: { ...card.learning_state, progress: [progress], next_actions: [] },
    course_progress: { ...card.course_progress, sections: [identity], next_request_id: null },
    sections: [{ heading: "Legacy projection marker", content: "Legacy sample content." }] }
}

const shellRows = {
  course: [
    ["I.1", "Part I · Fundamentals", "concept", "skipped", "outside_requested_part"],
    ["II.1", "Permutation importance", "concept", "explained"],
    ["II.2", "Leakage detection", "concept", "explained"],
    ["II.3", "Shapley value calculation", "worked_calculation", "partial"],
    ["II.4", "SHAP waterfall", "figure_walkthrough", "not_generated"],
    ["II.5", "Work through the example", "exercise", "not_generated"],
    ["II.6", "LIME and SHAP", "comparison", "not_generated"],
    ["II.7", "Model limitations", "concept", "not_generated"],
    ["III.1", "Part III · Interpretable models", "concept", "skipped", "outside_requested_part"],
    ["IV.1", "Part IV · Auditability", "concept", "skipped", "outside_requested_part"],
    ["", "Recap", "summary", "skipped", "non_teaching"],
  ],
  exercises: [
    ["Exercice 1", "Confusion matrix", "exercise", "explained"],
    ["1.a", "Calculate precision", "exercise", "explained"],
    ["1.b", "Calculate the F1 score", "exercise", "explained"],
    ["Exercice 2", "Compare the two models", "exercise", "explained"],
    ["2.a", "Compare precision", "exercise", "partial"],
    ["2.b", "Discuss the trade-off", "exercise", "not_generated"],
    ["Exercice 3", "Exercise 3 · SHAP", "exercise", "skipped", "exercise_excluded"],
  ],
  lab: [
    ["Étape 1", "Import the data in KNIME", "lab_step", "explained"],
    ["Étape 2", "Configure the partition", "lab_step", "partial"],
    ["Étape 3", "Train the model", "lab_step", "not_generated"],
    ["Étape 4", "Export the workflow", "lab_step", "not_generated"],
  ],
}

export function documentFixture(shell) {
  const document_id = "pdf-" + shell
  const source_hash = "fixture-source"
  const request_id = "saved-" + shell
  const generation = 3
  const rows = shellRows[shell].map(([label, title, kind, status, reason = "requested"], index) => {
    const logical_id = shell + "-" + index
    const page = index + 1
    const identity = { id: logical_id, content_version: "content-" + logical_id, label, kind, title, start: page, end: page,
      ...(shell === "exercises" && label === "1.b" ? { depends_on: [shell + "-1"] } : {}) }
    const missing_item_ids = status === "partial" ? [shell + "-missing-item"] : []
    const unverifiable_source = status === "partial" && shell === "lab" ? [{ page, status: "unverifiable_source", reason: "preparation_pending" }] : []
    const verification = status === "explained" ? "reviewed" : status === "partial" ? "review_failed" :
      status === "skipped" ? "not_applicable" : "unreviewed"
    const progress = { logical_id, content_version: identity.content_version, pages: [page, page], status, title, scope_reason: reason,
      verification, missing_item_ids, unverifiable_source }
    return { identity, progress }
  })
  const units = rows.filter(({ progress }) => ["explained", "partial"].includes(progress.status)).map(({ identity, progress }) => {
    const [base] = instructionalFixture(identity.kind).units
    const { logical_id, content_version, title, status, verification, missing_item_ids, unverifiable_source } = progress
    const blocks = base.blocks.filter((block) => !(shell === "lab" && status === "partial" && block.kind === "checkpoint"))
    if (shell === "lab" && status === "explained") blocks.push({
      block_id: logical_id + "-deliverable", kind: "deliverable", text: "Save the configured KNIME workflow.",
      provenance: "course", source_indexes: [1],
    })
    return { ...base, logical_id, content_version, title, coverage: status, verification,
      missing_item_ids, unverifiable_source, blocks, sources: [{ ...base.sources[0], page: progress.pages[0] }] }
  })
  const progress = rows.map((row) => row.progress)
  const partial = progress.filter((row) => row.status === "partial")
  const remaining = progress.filter((row) => row.status === "not_generated")
  const scopes = Object.fromEntries(progress.map((row) => [row.logical_id, { in_scope: row.status !== "skipped", reason: row.scope_reason }]))
  const next_actions = [{ action: "continue_learning", logical_id: remaining[0].logical_id, request_id: "continue-" + shell, attempt: 1 },
    { action: "deepen_unit", logical_id: partial[0].logical_id, request_id: "deepen-" + shell, attempt: 2 }]
  const versions = units.map((output) => ({ request_id, stage: "ready", output, change_log: [], document_id, source_hash, generation,
    identity: rows.find(({ identity }) => identity.id === output.logical_id).identity }))
  const count = (field) => progress.reduce((counts, row) => ({ ...counts, [row[field]]: (counts[row[field]] ?? 0) + 1 }), {})
  const card = { ...empty, schema_version: 2, language: "French", presentation: "full_course", units, versions,
    sections: [{ heading: "Legacy projection only", content: "Duplicate fallback content." }],
    course_progress: { document_id, request_id, source_hash, index_generation: generation, part: 1, total_parts: 3,
      next_request_id: next_actions[0].request_id, sections: rows.filter((row) => row.progress.status !== "skipped").map((row) => row.identity),
      learning_plan: { assumptions: shell === "course" ? ["Part II follows the source headings."] : [],
        order: progress.filter((row) => row.status !== "skipped").map((row) => row.logical_id), scope: scopes,
        level: "intermediate", depth: "exhaustive", required_items: {}, unverifiable_source: {}, remaining,
        next_actions, facts_ledger: [] } },
    learning_state: { progress, next_actions, facts: { verified_facts: shell === "exercises" ? [
      { unit_id: "exercises-2", content_version: "content-exercises-2", label_path: ["1.b", "F1"], value: "0,80",
        verification: "deterministic_only" },
      { unit_id: "exercises-4", content_version: "content-exercises-4", label_path: ["2.a"], value: "invalid sample value",
        verification: "unreviewed" },
    ] : [] } },
    coverage_ledger: { coverage_counts: count("status"), verification_counts: count("verification"),
      partial, remaining, low_fidelity_pages: shell === "lab" ? [2] : [], corrections: [], skipped_optional_items: {}, next_actions },
  }
  const checking = { request_id: next_actions[0].request_id, stage: "draft", document_id, source_hash, generation,
    output: { ...units[0], logical_id: remaining[0].logical_id, content_version: remaining[0].content_version,
      title: remaining[0].title, coverage: "partial", verification: "unreviewed" } }
  return { card, checking }
}
