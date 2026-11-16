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
