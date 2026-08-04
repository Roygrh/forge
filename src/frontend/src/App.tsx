/**
 * Two screens, and a hash for a router.
 *
 * `#/` is the catalog and `#/runs/<id>` is one run's trace. A router library would be
 * two routes' worth of dependency; a hash keeps a run's URL reloadable, shareable and
 * back-button-correct, which is the entire requirement.
 */

import { useCallback, useEffect, useState } from 'react'

import { Shell } from './components/Shell'
import { AgentsScreen } from './screens/AgentsScreen'
import { RunScreen } from './screens/RunScreen'

type Route = { name: 'agents' } | { name: 'run'; runId: string }

function parseRoute(hash: string): Route {
  const match = /^#\/runs\/([^/?#]+)/.exec(hash)
  return match?.[1] === undefined ? { name: 'agents' } : { name: 'run', runId: match[1] }
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
    <Shell>
      {route.name === 'run' ? (
        <RunScreen runId={route.runId} onBack={openAgents} />
      ) : (
        <AgentsScreen onRunStarted={openRun} />
      )}
    </Shell>
  )
}
