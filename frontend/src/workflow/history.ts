export type WorkflowPhase = 'upload' | 'processing' | 'results'

const HISTORY_KEY = 'supplierDocumentChecker'

interface HistoryPort {
  readonly state: unknown
  pushState(data: unknown, unused: string): void
  replaceState(data: unknown, unused: string): void
}

/** Return the app phase stored on this history entry, if it belongs to this workflow. */
export function workflowPhaseFromHistory(state: unknown): WorkflowPhase | null {
  if (typeof state !== 'object' || state === null || Array.isArray(state)) return null
  const value = (state as Record<string, unknown>)[HISTORY_KEY]
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const phase = (value as { phase?: unknown }).phase
  return phase === 'upload' || phase === 'processing' || phase === 'results' ? phase : null
}

/** Keep one upload entry behind later workflow states so Back returns into the app. */
export function ensureUploadHistoryEntry(history: HistoryPort): void {
  const phase = workflowPhaseFromHistory(history.state)
  if (phase === null) {
    writeWorkflowPhase(history, 'upload', false)
  } else if (phase !== 'upload') {
    writeWorkflowPhase(history, 'upload', true)
  }
}

export function pushWorkflowPhase(history: HistoryPort, phase: WorkflowPhase): void {
  writeWorkflowPhase(history, phase, false)
}

export function replaceWorkflowPhase(history: HistoryPort, phase: WorkflowPhase): void {
  writeWorkflowPhase(history, phase, true)
}

function writeWorkflowPhase(
  history: HistoryPort,
  phase: WorkflowPhase,
  replace: boolean,
): void {
  const state =
    typeof history.state === 'object' && history.state !== null && !Array.isArray(history.state)
      ? { ...(history.state as Record<string, unknown>) }
      : {}
  state[HISTORY_KEY] = { phase }
  if (replace) history.replaceState(state, '')
  else history.pushState(state, '')
}
