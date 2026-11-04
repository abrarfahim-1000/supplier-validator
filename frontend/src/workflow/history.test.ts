import { describe, expect, it } from 'vitest'
import {
  ensureUploadHistoryEntry,
  pushWorkflowPhase,
  replaceWorkflowPhase,
  workflowPhaseFromHistory,
} from './history'

class MemoryHistory {
  entries: unknown[] = []
  index = -1

  get state(): unknown {
    return this.entries[this.index] ?? null
  }

  pushState(data: unknown): void {
    this.entries = this.entries.slice(0, this.index + 1)
    this.entries.push(data)
    this.index += 1
  }

  replaceState(data: unknown): void {
    this.entries[this.index] = data
  }

  back(): void {
    this.index = Math.max(0, this.index - 1)
  }
}

describe('workflow history', () => {
  it('keeps the upload phase behind processing and results', () => {
    const history = new MemoryHistory()
    ensureUploadHistoryEntry(history)
    pushWorkflowPhase(history, 'processing')
    replaceWorkflowPhase(history, 'results')

    history.back()

    expect(workflowPhaseFromHistory(history.state)).toBe('upload')
  })

  it('does not add duplicate upload entries when initialized more than once', () => {
    const history = new MemoryHistory()
    ensureUploadHistoryEntry(history)
    ensureUploadHistoryEntry(history)

    expect(history.entries).toHaveLength(1)
    expect(workflowPhaseFromHistory(history.state)).toBe('upload')
  })

  it('ignores history entries from outside this workflow', () => {
    expect(workflowPhaseFromHistory({ someOtherPage: true })).toBeNull()
  })
})
