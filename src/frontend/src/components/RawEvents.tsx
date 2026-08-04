/**
 * The append-only event log the timeline above was projected from (ADR-008).
 *
 * This panel is the reason the trace can be trusted rather than believed: the API serves
 * the projection *and* its source, so a reviewer can check one against the other on the
 * same screen. Note that there are more events here than steps — `run.started` and the
 * terminal event are lifecycle, not reasoning, and the projection says so by omitting
 * them from the timeline while the log still carries them.
 */

import type { RunEvent } from '../api/types'
import { formatDateTime } from '../lib/format'
import { Disclosure } from './Disclosure'
import { JsonBlock } from './Json'

/** Events that project into a timeline step, versus events that are pure lifecycle. */
const STEP_EVENT_TYPES = new Set(['model.called', 'tool.called', 'decision.made'])

export function RawEventsPanel({ events }: { events: RunEvent[] }) {
  const stepEvents = events.filter((event) => STEP_EVENT_TYPES.has(event.type)).length

  return (
    <section className="rounded-lg border border-slate-200 bg-white px-5 py-4">
      <Disclosure
        summary="Raw events — the audit log this trace was projected from"
        hint={`${events.length} appended · ${stepEvents} became steps`}
      >
        <p className="mb-4 max-w-3xl text-sm leading-relaxed text-slate-600">
          The <code className="font-mono text-[12px]">events</code> table is append-only in the
          database itself — the application role holds no <code className="font-mono text-[12px]">UPDATE</code>{' '}
          or <code className="font-mono text-[12px]">DELETE</code> grant, and a trigger rejects both
          (ADR-008). The timeline above is derived from these rows and nothing else, so what the
          screen shows is what was actually recorded.
        </p>

        <ol className="space-y-2">
          {events.map((event) => (
            <li key={event.event_id} className="rounded-md border border-slate-200 bg-slate-50/70">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2">
                <span
                  title="Monotonic event id — the ordering is part of the audit contract"
                  className="font-mono text-xs text-slate-400 tabular-nums"
                >
                  #{event.event_id}
                </span>
                <span className="font-mono text-[13px] font-medium text-slate-800">
                  {event.type}
                </span>
                {!STEP_EVENT_TYPES.has(event.type) && (
                  <span
                    title="A lifecycle event: real and appended, but not a reasoning step"
                    className="rounded bg-slate-200/70 px-1.5 py-0.5 text-[11px] font-medium text-slate-600"
                  >
                    lifecycle
                  </span>
                )}
                <span className="ml-auto text-xs text-slate-500">
                  <span title="The actor recorded on this event">{event.actor}</span>
                  {' · '}
                  {formatDateTime(event.occurred_at)}
                </span>
              </div>
              <div className="px-3.5 pb-3">
                <JsonBlock value={event.payload} />
              </div>
            </li>
          ))}
        </ol>
      </Disclosure>
    </section>
  )
}
