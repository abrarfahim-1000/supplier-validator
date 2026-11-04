import { describe, expect, it } from 'vitest'
import { HEALTH_RETRY_DELAYS_MS, healthRetryDelay } from './health'

describe('healthRetryDelay', () => {
  it('backs off further with every failed attempt', () => {
    expect(healthRetryDelay(0)).toBe(1000)
    expect(healthRetryDelay(2)).toBe(4000)
    expect(healthRetryDelay(5)).toBe(30000)
  })

  it('stops after the last attempt instead of retrying forever', () => {
    expect(healthRetryDelay(HEALTH_RETRY_DELAYS_MS.length)).toBeUndefined()
    expect(healthRetryDelay(99)).toBeUndefined()
  })

  it('waits a minute in total before giving up', () => {
    const total = HEALTH_RETRY_DELAYS_MS.reduce((sum, delay) => sum + delay, 0)
    expect(total).toBe(60000)
  })
})
