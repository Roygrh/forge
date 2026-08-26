/**
 * The demo story: the pre-composed runs a presenter can start without typing anything.
 *
 * Mirrored by hand from `src/backend/app/demo_story.py`, which is the source of truth —
 * the same convention, and the same justification, as `api/types.ts` against
 * `app/api/schemas.py`. The backend copy is the one under test: `tests/test_demo_story.py`
 * executes every entry below through the real runtime and asserts the outcome, so a beat
 * that stops behaving fails the build rather than failing on stage.
 *
 * Nothing here invents data. Every invoice named below was already frozen in
 * `app/erp/seed_data.py` for an evaluation case; what this file adds is the *order* and
 * the *label* — so nobody has to hunt through a list mid-sentence.
 *
 * `docs/demo-script.md` is the presenter-facing form. Change a beat, change all three.
 */

export interface DemoRun {
  /** Position in the five-beat story, or `null` for a supporting run outside it. */
  beat: number | null
  /** Stable identifier, used as the `<option>` value. */
  key: string
  /** What the presenter reads in the picker. */
  label: string
  /** The one line this run exists to land. */
  point: string
  agentSlug: string
  /** Exactly what is sent as the run input. */
  input: Record<string, string>
}

const COMMS_QUESTION = 'Which purchase order covers the price difference on this invoice?'
const POLICY_QUESTION = 'What is the invoice approval threshold amount requiring manager approval?'

export const DEMO_RUNS: readonly DemoRun[] = [
  {
    beat: 1,
    key: 'clean',
    label: 'INV-4401 — clean approval',
    point: 'It works — and it tells you which rules let it.',
    agentSlug: 'invoice-validator',
    input: { invoice_id: 'inv-0001' },
  },
  {
    beat: 2,
    key: 'threshold',
    label: 'INV-4409 — $12,000, over policy',
    point: 'Same vendor, same perfect match. Trust does not beat policy.',
    agentSlug: 'invoice-validator',
    input: { invoice_id: 'inv-0009' },
  },
  {
    beat: 3,
    key: 'duplicate',
    label: 'INV-4471 — duplicate invoice number',
    point: 'It stopped, and approve_invoice was never called.',
    agentSlug: 'invoice-validator',
    input: { invoice_id: 'inv-0015' },
  },
  {
    beat: 4,
    key: 'human',
    label: 'INV-4405 — ask the vendor (needs a person)',
    point: 'The message is written, and it is not sent. A person decides.',
    agentSlug: 'invoice-comms',
    input: { invoice_id: 'inv-0005', question: COMMS_QUESTION },
  },
  {
    beat: 5,
    key: 'conflict',
    label: 'Policy question — which approval threshold governs?',
    point: 'Three sources disagreed. Authority decided, and the loser stays on the record.',
    agentSlug: 'invoice-validator',
    input: { question: POLICY_QUESTION },
  },
  {
    beat: null,
    key: 'intake',
    label: 'INV-4401 — normalise for validation',
    point: 'Intake may read an invoice and nothing else.',
    agentSlug: 'invoice-intake',
    input: { invoice_id: 'inv-0001' },
  },
  {
    beat: null,
    key: 'revoked',
    label: 'INV-4401 — the same invoice, approval revoked',
    point: 'One line of the definition changed, and the gateway refuses the call.',
    agentSlug: 'invoice-validator-restricted',
    input: { invoice_id: 'inv-0001' },
  },
]

/**
 * The skeleton agent's payload, and the answer for any agent this build has never heard
 * of. A catalog containing an agent added after this bundle was built still gets a
 * working button rather than a broken one.
 */
const FALLBACK: DemoRun = {
  beat: null,
  key: 'default',
  label: 'Default input',
  point: 'No story input is defined for this agent in this build.',
  agentSlug: '',
  input: { topic: 'governance' },
}

/**
 * The runs offered for one agent, in presentation order — never empty, so the caller can
 * read the first entry as the default selection without a null check.
 */
export function runsFor(agentSlug: string): readonly [DemoRun, ...DemoRun[]] {
  const [first, ...rest] = DEMO_RUNS.filter((run) => run.agentSlug === agentSlug)
  return first === undefined ? [FALLBACK] : [first, ...rest]
}
