/**
 * Four screens, and a hash for a router.
 *
 * `#/` is the catalog, `#/approvals` is the queue a person works, `#/evals` is the
 * suite and its publish gate, and `#/runs/<id>` is one run's trace. A router library
 * would be four routes' worth of dependency; a hash keeps every screen's URL
 * reloadable, shareable and back-button-correct, which is the entire requirement.
 */

import { useCallback, useEffect, useState } from 'react'

import { Shell } from './components/Shell'
import { AgentsScreen } from './screens/AgentsScreen'
import { ApprovalsScreen } from './screens/ApprovalsScreen'
import { EvalsScreen } from './screens/EvalsScreen'
import { RunScreen } from './screens/RunScreen'

type Route =
  | { name: 'agents' }
  | { name: 'approvals' }
  | { name: 'evals' }
  | { name: 'run'; runId: string }

function parseRoute(hash: string): Route {
  const run = /^#\/runs\/([^/?#]+)/.exec(hash)
  if (run?.[1] !== undefined) return { name: 'run', runId: run[1] }
  if (/^#\/approvals\b/.test(hash)) return { name: 'approvals' }
  if (/^#\/evals\b/.test(hash)) return { name: 'evals' }
  return { name: 'agents' }
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash))

  useEffect(() => {
    const onHashChange = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  // Navigation goes through the hash, never through setRoute alone, so the address bar
  // and the rendered screen cannot disagree.
  const navigate = useCallback((hash: string) => {
    window.location.hash = hash
  }, [])

  const openRun = useCallback((runId: string) => navigate(`#/runs/${runId}`), [navigate])
  const openAgents = useCallback(() => navigate('#/'), [navigate])

  return (
    <Shell active={route.name}>
      {route.name === 'run' && <RunScreen runId={route.runId} onBack={openAgents} />}
      {route.name === 'approvals' && <ApprovalsScreen onOpenRun={openRun} />}
      {route.name === 'evals' && <EvalsScreen onOpenRun={openRun} />}
      {route.name === 'agents' && <AgentsScreen onRunStarted={openRun} />}
    </Shell>
  )
}
