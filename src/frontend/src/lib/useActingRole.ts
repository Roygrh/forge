import { useSyncExternalStore } from 'react'

import { getActingRole, subscribeToRole } from '../api/client'
import type { Role } from '../api/types'

/**
 * The role every request is currently sent as, as React state.
 *
 * `useSyncExternalStore` rather than a context: the role lives in the API client because
 * that is what puts it on the wire, and a screen that renders it should read the same
 * variable rather than a copy that could disagree with what was actually sent.
 */
export function useActingRole(): Role {
  return useSyncExternalStore(subscribeToRole, getActingRole, getActingRole)
}
