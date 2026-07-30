import { useEffect } from 'react'

// Topics after which the run is over and the server closes the stream.
const TERMINAL_TOPICS = new Set(['engagement.completed', 'engagement.rejected'])

/**
 * Subscribe to the SSE event stream for a running engagement.
 * onEvent is called for each parsed event object from the server.
 * The connection is closed when runId changes, the component unmounts, or the
 * engagement reaches a terminal event.
 */
export function useEvents(runId, onEvent) {
  useEffect(() => {
    if (!runId) return

    let done = false
    const es = new EventSource(`/engagements/${runId}/events`)

    es.onmessage = (e) => {
      let event
      try {
        event = JSON.parse(e.data)
      } catch (err) {
        console.warn('SSE: dropping malformed event', err)
        return
      }
      onEvent(event)
      // The server ends the stream after a terminal event; close our side too so the
      // EventSource doesn't keep auto-reconnecting to a finished run.
      if (TERMINAL_TOPICS.has(event?.topic)) {
        done = true
        es.close()
      }
    }

    es.onerror = () => {
      // Do NOT close on a transient error — that would defeat EventSource's built-in
      // auto-reconnect and silently freeze the UI after any network blip (the run keeps
      // going server-side, but we'd never hear about it). Let it reconnect; the server
      // re-emits terminal state on connect if the run already finished. Only stop once
      // we've seen the terminal event ourselves.
      if (done) es.close()
    }

    return () => { done = true; es.close() }
  }, [runId]) // onEvent intentionally excluded — caller must stabilise with useCallback
}
