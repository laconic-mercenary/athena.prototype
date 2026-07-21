import { useEffect } from 'react'

/**
 * Subscribe to the SSE event stream for a running engagement.
 * onEvent is called for each parsed event object from the server.
 * The connection is closed when runId changes or the component unmounts.
 */
export function useEvents(runId, onEvent) {
  useEffect(() => {
    if (!runId) return

    const es = new EventSource(`/engagements/${runId}/events`)

    es.onmessage = (e) => {
      try {
        onEvent(JSON.parse(e.data))
      } catch {
        // malformed event — ignore
      }
    }

    es.onerror = () => {
      // Server closed stream or network error; close cleanly
      es.close()
    }

    return () => es.close()
  }, [runId]) // onEvent intentionally excluded — caller must stabilise with useCallback
}
