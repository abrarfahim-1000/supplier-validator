import { useEffect, useRef, useState } from 'react'
import { ApiError, getJobResults } from '@/api/client'
import type { DocumentResult, JobStatusResponse } from '@/api/client'
import { ProcessingStage } from './processing-stage'
import { ResultsDashboard } from './results-dashboard'
import { UploadStage } from './upload-stage'
import { addQuotations } from '@/ui/files'
import { AnalysisError, getResultsWithRetry, runAnalysis } from '@/workflow/analysis'
import {
  ensureUploadHistoryEntry,
  pushWorkflowPhase,
  replaceWorkflowPhase,
  workflowPhaseFromHistory,
} from '@/workflow/history'
import type { ServiceHealth } from '@/workflow/health'
import { MAX_QUOTATIONS } from '@/workflow/limits'

type Phase = 'upload' | 'processing' | 'results'

function describeFailure(error: unknown): string {
  if (error instanceof ApiError || error instanceof AnalysisError) {
    return error.message
  }
  return 'The validation service could not complete the run. Try again.'
}

export function CheckerPage({ service }: { service: ServiceHealth }) {
  const [phase, setPhase] = useState<Phase>('upload')
  const [purchaseRequest, setPurchaseRequest] = useState<File | null>(null)
  const [quotations, setQuotations] = useState<File[]>([])
  const [status, setStatus] = useState<JobStatusResponse | null>(null)
  const [results, setResults] = useState<readonly DocumentResult[] | null>(null)
  const [connectionInterrupted, setConnectionInterrupted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const resultsRef = useRef<HTMLDivElement | null>(null)
  const cachedResultsRef = useRef<readonly DocumentResult[] | null>(null)

  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    ensureUploadHistoryEntry(window.history)

    const handlePopState = () => {
      const historyPhase = workflowPhaseFromHistory(window.history.state)
      if (historyPhase === null) return

      if (historyPhase === 'results' && cachedResultsRef.current !== null) {
        setPhase('results')
        setStatus(null)
        setConnectionInterrupted(false)
        setError(null)
        return
      }

      // A stale result or processing entry cannot be restored after its data was cleared.
      if (historyPhase !== 'upload') {
        replaceWorkflowPhase(window.history, 'upload')
      }
      abortRef.current?.abort()
      setPhase('upload')
      setStatus(null)
      setConnectionInterrupted(false)
      setError(null)
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    if (phase !== 'results' || !resultsRef.current) {
      return
    }
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    resultsRef.current.scrollIntoView({
      behavior: reduceMotion ? 'auto' : 'smooth',
      block: 'start',
    })
  }, [phase])

  const choosePurchaseRequest = (file: File | null) => {
    cachedResultsRef.current = null
    setResults(null)
    setPurchaseRequest(file)
    setError(null)
  }

  const addQuotationFiles = (files: File[]) => {
    const { files: next, messages } = addQuotations(quotations, files, MAX_QUOTATIONS)
    const changed = next.length !== quotations.length || next.some((file, index) => file !== quotations[index])
    if (changed) {
      cachedResultsRef.current = null
      setResults(null)
    }
    setQuotations(next)
    setError(messages.length > 0 ? messages.join(' ') : null)
  }

  const removeQuotation = (index: number) => {
    cachedResultsRef.current = null
    setResults(null)
    setQuotations((current) => current.filter((_, fileIndex) => fileIndex !== index))
    setError(null)
  }

  const run = async () => {
    if (!purchaseRequest || quotations.length === 0 || phase === 'processing') {
      return
    }

    const controller = new AbortController()
    abortRef.current = controller
    pushWorkflowPhase(window.history, 'processing')
    setPhase('processing')
    setStatus(null)
    cachedResultsRef.current = null
    setResults(null)
    setConnectionInterrupted(false)
    setError(null)

    try {
      const finished = await runAnalysis({
        purchaseRequest,
        supplierQuotes: quotations,
        signal: controller.signal,
        onStatus: setStatus,
        onConnectionInterrupted: setConnectionInterrupted,
      })
      const payload = await getResultsWithRetry(
        () => getJobResults(finished.id, controller.signal),
        { signal: controller.signal, onConnectionInterrupted: setConnectionInterrupted },
      )
      cachedResultsRef.current = payload.results
      setResults(payload.results)
      replaceWorkflowPhase(window.history, 'results')
      setPhase('results')
    } catch (caught) {
      if (controller.signal.aborted) {
        return
      }
      setError(describeFailure(caught))
      setStatus(null)
      cachedResultsRef.current = null
      setResults(null)
      setConnectionInterrupted(false)
      replaceWorkflowPhase(window.history, 'upload')
      setPhase('upload')
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null
      }
    }
  }

  const restart = () => {
    if (workflowPhaseFromHistory(window.history.state) === 'results') {
      window.history.back()
    } else {
      replaceWorkflowPhase(window.history, 'upload')
    }
    setPhase('upload')
    cachedResultsRef.current = null
    setResults(null)
    setStatus(null)
    setConnectionInterrupted(false)
    setError(null)
    setPurchaseRequest(null)
    setQuotations([])
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <>
      {phase === 'upload' ? (
        <UploadStage
          purchaseRequest={purchaseRequest}
          quotations={quotations}
          service={service.state}
          error={error}
          onPurchaseRequest={choosePurchaseRequest}
          onQuotations={addQuotationFiles}
          onRemoveQuotation={removeQuotation}
          onReject={setError}
          onRun={run}
        />
      ) : null}

      {phase === 'processing' ? (
        <ProcessingStage status={status} connectionInterrupted={connectionInterrupted} />
      ) : null}

      {phase === 'results' && results ? (
        <div ref={resultsRef}>
          <ResultsDashboard results={results} onRestart={restart} />
        </div>
      ) : null}
    </>
  )
}
