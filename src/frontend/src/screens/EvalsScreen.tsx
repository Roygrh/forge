/**
 * The eval suite and the publish gate, on one screen (FR-F1, FR-F2).
 *
 * Top to bottom it answers the three questions a reviewer asks: which suite governs,
 * how the selected version scored on it — per case, expected vs actual, with the exact
 * failed assert named — and whether that version may therefore be published. The
 * publish button is disabled with its reason while the gate is unmet, but the button
 * state is a courtesy, not the control: the server answers 409 to anyone who calls the
 * endpoint anyway, and what this screen renders on that refusal is the server's own
 * error body.
 */

import { useCallback, useEffect, useState } from 'react'

import { api } from '../api/client'
import type {
  Agent,
  AgentVersion,
  DecisionAction,
  EvalCaseResult,
  EvalRun,
  EvalSuite,
} from '../api/types'
import { Disclosure } from '../components/Disclosure'
import { Empty, ErrorNotice, Loading } from '../components/Feedback'
import { Mono } from '../components/Json'
import {
  DecisionActionPill,
  EvalRunStatusPill,
  Pill,
  VerdictPill,
  VersionStatusPill,
} from '../components/Pill'
import { Button, PageHeading } from '../components/Shell'
import { formatDateTime } from '../lib/format'
import { useAsync } from '../lib/useAsync'

interface VersionOption {
  agent: Agent
  version: AgentVersion
}

interface Catalog {
  suites: EvalSuite[]
  options: VersionOption[]
}

async function loadCatalog(): Promise<Catalog> {
  const [suites, agents] = await Promise.all([api.listEvalSuites(), api.listAgents()])
  const versionLists = await Promise.all(agents.map((agent) => api.listVersions(agent.id)))
  const options = agents.flatMap((agent, index) =>
    (versionLists[index] ?? []).map((version) => ({ agent, version })),
  )
  return { suites, options }
}

const keyOf = (option: VersionOption) => option.version.id

export function EvalsScreen({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const { state, reload } = useAsync(useCallback(loadCatalog, []))

  return (
    <>
      <PageHeading
        eyebrow="Evaluation"
        title="Eval suite & publish gate"
        lead={
          <>
            The 20 cases of the AP suite were written before the agents existed, and they are
            the publish gate: a version ships only after every case passes, and the passing run
            is recorded as the publish’s evidence. Each case executes a real run of the version
            under test — deterministic, offline, scored by programmatic asserts — so a verdict
            here is reproducible, not sampled.
          </>
        }
      />

      {state.status === 'loading' && <Loading label="Loading suites and versions…" />}
      {state.status === 'error' && <ErrorNotice error={state.error} onRetry={reload} />}
      {state.status === 'ready' &&
        (state.data.suites.length === 0 ? (
          <Empty title="No eval suites installed">
            Seed the suite with{' '}
            <code className="font-mono text-[12px]">
              docker compose exec api python -m scripts.seed
            </code>
            .
          </Empty>
        ) : (
          <SuiteBoard catalog={state.data} onCatalogChanged={reload} onOpenRun={onOpenRun} />
        ))}
    </>
  )
}

function SuiteBoard({
  catalog,
  onCatalogChanged,
  onOpenRun,
}: {
  catalog: Catalog
  onCatalogChanged: () => void
  onOpenRun: (runId: string) => void
}) {
  // One suite ships today; the selector appears only if that ever changes.
  const suite = catalog.suites[0]
  const [selectedKey, setSelectedKey] = useState<string | null>(() => {
    const firstDraft = catalog.options.find((option) => option.version.status === 'draft')
    return keyOf(firstDraft ?? catalog.options[0] ?? { version: { id: '' } } as VersionOption) || null
  })
  const selected =
    catalog.options.find((option) => keyOf(option) === selectedKey) ?? catalog.options[0]

  const [evalRuns, setEvalRuns] = useState<EvalRun[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [running, setRunning] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)

  const refreshRuns = useCallback(async (versionId: string) => {
    setLoadError(null)
    try {
      setEvalRuns(await api.listEvalRuns(versionId))
    } catch (cause) {
      setEvalRuns(null)
      setLoadError(cause)
    }
  }, [])

  useEffect(() => {
    if (selected !== undefined) void refreshRuns(selected.version.id)
  }, [selected, refreshRuns])

  if (suite === undefined || selected === undefined) {
    return <Empty title="Nothing to evaluate">Seed the demonstration agents first.</Empty>
  }

  const latest = evalRuns?.find((run) => run.status === 'completed') ?? evalRuns?.[0] ?? null

  const runSuite = async () => {
    setRunning(true)
    setActionError(null)
    try {
      // Executes inline: the response already carries the verdict.
      await api.runEvalSuite(suite.id, {
        agent_id: selected.agent.id,
        version: selected.version.version,
      })
      await refreshRuns(selected.version.id)
    } catch (cause) {
      setActionError(cause)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-slate-200 bg-white px-6 py-5 shadow-xs">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-slate-900">Suite</h2>
              <Mono>
                {suite.slug}@{suite.version}
              </Mono>
              <Pill tone="neutral">{suite.case_count} cases</Pill>
            </div>
            <p className="mt-1.5 text-sm text-slate-600">{suite.name}</p>
          </div>

          <label className="flex items-center gap-2 text-sm text-slate-600">
            Version under test
            <select
              value={selected.version.id}
              onChange={(event) => setSelectedKey(event.target.value)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm font-medium text-slate-700 focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:outline-none"
            >
              {catalog.options.map((option) => (
                <option key={keyOf(option)} value={option.version.id}>
                  {option.agent.slug}@{option.version.version} ({option.version.status})
                </option>
              ))}
            </select>
          </label>

          <Button onClick={() => void runSuite()} disabled={running}>
            {running ? 'Scoring 20 cases…' : 'Run suite'}
          </Button>
        </div>

        {actionError !== null && (
          <div className="mt-4">
            <ErrorNotice error={actionError} />
          </div>
        )}
      </section>

      <PublishPanel
        selected={selected}
        latest={latest}
        onPublished={onCatalogChanged}
      />

      {loadError !== null && <ErrorNotice error={loadError} />}
      {evalRuns !== null && latest === null && (
        <Empty title="No eval run for this version yet">
          Run the suite to score it — the publish gate stays shut until every case passes.
        </Empty>
      )}
      {latest !== null && <EvalRunCard evalRun={latest} onOpenRun={onOpenRun} />}
    </div>
  )
}

/**
 * The gate, stated as the server will enforce it.
 *
 * Disabled-with-reason mirrors the 409 the endpoint would answer; a seeded published
 * version is labelled as the documented exception its null eval-run evidence marks.
 */
function PublishPanel({
  selected,
  latest,
  onPublished,
}: {
  selected: VersionOption
  latest: EvalRun | null
  onPublished: () => void
}) {
  const { agent, version } = selected
  const [publishing, setPublishing] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [published, setPublished] = useState<AgentVersion | null>(null)

  const current = published ?? version
  const gateMet = latest !== null && latest.status === 'completed' && latest.passed === true

  const publish = async () => {
    setPublishing(true)
    setError(null)
    try {
      setPublished(await api.publishVersion(agent.id, version.version))
      onPublished()
    } catch (cause) {
      // A 409 here is the gate itself speaking; render the server's body verbatim.
      setError(cause)
    } finally {
      setPublishing(false)
    }
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white px-6 py-5 shadow-xs">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold text-slate-900">Publish gate</h2>
            <Mono>
              {agent.slug}@{current.version}
            </Mono>
            <VersionStatusPill status={current.status} />
          </div>
          <p className="mt-1.5 text-sm text-slate-600">
            {current.status === 'published' ? (
              current.published_eval_run_id === null ? (
                <>
                  Published by the seed script — the one documented exception to the gate,
                  visible here by its missing eval-run evidence.
                </>
              ) : (
                <>
                  Published{current.published_at !== null && ` ${formatDateTime(current.published_at)}`},
                  on the evidence of passing eval run{' '}
                  <span className="font-mono text-[12px]">{current.published_eval_run_id}</span>.
                </>
              )
            ) : current.status === 'draft' ? (
              gateMet ? (
                <>Every case passed — this draft has earned its publish.</>
              ) : latest === null ? (
                <>
                  Gate unmet: no completed eval run exists for this version. Publishing now
                  would be refused by the server with 409 <Mono>publish_gate_unmet</Mono>.
                </>
              ) : latest.status !== 'completed' ? (
                <>Gate unmet: the latest eval run has not finished scoring.</>
              ) : (
                <>
                  Gate unmet: the latest eval run failed{' '}
                  {latest.passed_count !== null && latest.total !== null && (
                    <>
                      ({latest.passed_count}/{latest.total} cases passed)
                    </>
                  )}
                  . The server refuses publishing with 409 <Mono>publish_gate_unmet</Mono>, and
                  the version stays a draft.
                </>
              )
            ) : (
              <>
                This version is {current.status}; only a draft can be published. Author the
                next version to change behaviour.
              </>
            )}
          </p>
        </div>

        {current.status === 'draft' && (
          <Button
            onClick={() => void publish()}
            disabled={!gateMet || publishing}
          >
            {publishing ? 'Publishing…' : 'Publish'}
          </Button>
        )}
      </div>

      {error !== null && (
        <div className="mt-4">
          <ErrorNotice error={error} />
        </div>
      )}
    </section>
  )
}

function EvalRunCard({
  evalRun,
  onOpenRun,
}: {
  evalRun: EvalRun
  onOpenRun: (runId: string) => void
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-xs">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-6 py-4">
        <h2 className="text-base font-semibold text-slate-900">Latest eval run</h2>
        <EvalRunStatusPill status={evalRun.status} />
        {evalRun.passed === null ? (
          <VerdictPill passed={null} />
        ) : (
          <VerdictPill
            passed={evalRun.passed}
            label={`${evalRun.passed ? 'Passed' : 'Failed'} ${evalRun.passed_count ?? '—'}/${evalRun.total ?? '—'}`}
          />
        )}
        <span className="ml-auto text-xs text-slate-400">
          {formatDateTime(evalRun.created_at)} · <span className="font-mono">{evalRun.id}</span>
        </span>
      </div>

      {evalRun.case_results === null || evalRun.case_results.length === 0 ? (
        <div className="border-t border-slate-100 px-6 py-5 text-sm text-slate-500">
          No per-case results were recorded for this run.
        </div>
      ) : (
        <ul className="divide-y divide-slate-100 border-t border-slate-100">
          {evalRun.case_results.map((caseResult) => (
            <CaseRow key={caseResult.code} caseResult={caseResult} onOpenRun={onOpenRun} />
          ))}
        </ul>
      )}
    </section>
  )
}

/**
 * An action name as a pill. The union type guards this codebase; the cast is safe at
 * runtime because the pill's tone lookup falls back to neutral for unknown values —
 * an action a newer backend invents must render, not blank the table.
 */
function ActionPill({ action }: { action: string }) {
  return <DecisionActionPill action={action as DecisionAction} />
}

function CaseRow({
  caseResult,
  onOpenRun,
}: {
  caseResult: EvalCaseResult
  onOpenRun: (runId: string) => void
}) {
  const expectedMet = caseResult.actual_action === caseResult.expected_action
  return (
    <li className="px-6 py-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Mono>{caseResult.code}</Mono>
        <VerdictPill passed={caseResult.passed} />
        <span className="flex flex-wrap items-center gap-1.5 text-sm text-slate-600">
          expected <ActionPill action={caseResult.expected_action} />
          <span aria-hidden="true">→</span>
          actual{' '}
          {caseResult.actual_action === null ? (
            <Pill tone="bad" title="The run ended without reaching a decision — see its trace for the refusal that stopped it">
              no decision
            </Pill>
          ) : (
            <ActionPill action={caseResult.actual_action} />
          )}
          {!expectedMet && caseResult.actual_action !== null && (
            <Pill tone="bad">mismatch</Pill>
          )}
        </span>
        <button
          type="button"
          onClick={() => onOpenRun(caseResult.run_id)}
          className="ml-auto text-xs font-medium text-indigo-600 hover:text-indigo-800 focus-visible:ring-2 focus-visible:ring-indigo-400 focus-visible:outline-none"
        >
          Open run trace →
        </button>
      </div>
      <p className="mt-1.5 text-sm text-slate-600">{caseResult.scenario}</p>
      {!caseResult.passed && (
        <p className="mt-1.5 text-sm font-medium text-rose-700">{caseResult.detail}</p>
      )}

      <div className="mt-2">
        <Disclosure summary="Evidence" hint="citations, tools, and every assert">
          <div className="grid gap-x-8 gap-y-4 text-sm sm:grid-cols-2">
            <div>
              <h4 className="text-xs font-medium tracking-wide text-slate-500 uppercase">
                Citations
              </h4>
              <p className="mt-1.5 text-slate-700">
                required:{' '}
                {caseResult.expected_citations.length === 0 ? (
                  '—'
                ) : (
                  <CitationList
                    citations={caseResult.expected_citations}
                    present={caseResult.actual_citations}
                  />
                )}
              </p>
              <p className="mt-1 text-slate-700">
                cited:{' '}
                {caseResult.actual_citations.length === 0 ? (
                  '—'
                ) : (
                  <span className="font-mono text-[12px]">
                    {caseResult.actual_citations.join(', ')}
                  </span>
                )}
              </p>
            </div>
            <div>
              <h4 className="text-xs font-medium tracking-wide text-slate-500 uppercase">
                Tools
              </h4>
              <p className="mt-1.5 text-slate-700">
                called:{' '}
                <span className="font-mono text-[12px]">
                  {caseResult.tools_called.length === 0 ? '—' : caseResult.tools_called.join(', ')}
                </span>
              </p>
              <p className="mt-1 text-slate-700">
                must not call:{' '}
                <span className="font-mono text-[12px]">
                  {caseResult.must_not_call.length === 0 ? '—' : caseResult.must_not_call.join(', ')}
                </span>
              </p>
            </div>
          </div>

          <ul className="mt-4 space-y-1.5">
            {caseResult.checks.map((check) => (
              <li key={check.name} className="flex flex-wrap items-center gap-2 text-sm">
                <VerdictPill passed={check.passed} />
                <Mono>{check.name}</Mono>
                {check.detail !== 'ok' && <span className="text-slate-600">{check.detail}</span>}
              </li>
            ))}
          </ul>
        </Disclosure>
      </div>
    </li>
  )
}

/** Required citations, each marked by whether the decision actually carried it. */
function CitationList({ citations, present }: { citations: string[]; present: string[] }) {
  return (
    <span className="inline-flex flex-wrap gap-1.5 align-middle">
      {citations.map((citation) => (
        <Pill
          key={citation}
          tone={present.includes(citation) ? 'good' : 'bad'}
          title={
            present.includes(citation)
              ? 'Required and cited.'
              : 'Required but missing from the decision’s citations.'
          }
        >
          <span className="font-mono text-[11px]">{citation}</span>
        </Pill>
      ))}
    </span>
  )
}
