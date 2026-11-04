import { useCallback, useEffect, useState } from 'react'
import { getHealth } from '@/api/client'

export type ServiceState = 'starting' | 'ready' | 'down'

/**
 * The free-tier backend spins down when idle and can take about a minute to answer again.
 * These delays keep retrying for a minute of waiting, longer if a request itself hangs,
 * before the service is called unreachable.
 */
export const HEALTH_RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 15000, 30000] as const

/** `undefined` means the last attempt has already been made. */
export function healthRetryDelay(failures: number): number | undefined {
  return HEALTH_RETRY_DELAYS_MS[failures]
}

export interface ServiceHealth {
  state: ServiceState
  retry: () => void
}

/** Wakes the backend on load and keeps trying while it is cold-starting. */
export function useServiceHealth(): ServiceHealth {
  const [state, setState] = useState<ServiceState>('starting')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    let failures = 0

    const check = async () => {
      try {
        await getHealth()
        if (!cancelled) {
          setState('ready')
        }
      } catch {
        if (cancelled) {
          return
        }
        const delay = healthRetryDelay(failures)
        failures += 1
        if (delay === undefined) {
          setState('down')
          return
        }
        timer = window.setTimeout(() => {
          void check()
        }, delay)
      }
    }

    void check()

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [attempt])

  const retry = useCallback(() => {
    setState('starting')
    setAttempt((current) => current + 1)
  }, [])

  return { state, retry }
}
