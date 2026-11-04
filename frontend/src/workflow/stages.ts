/**
 * The five stage names mirror `checker.graph.STAGES`. The backend sends the names with
 * every status payload, so rendering uses those; this list documents the fixed order.
 */
export const PROCESSING_STAGES = [
  'Document Ingestion',
  'Information Extraction',
  'Purchase Request Comparison',
  'Company Rule Validation',
  'Decision Generation',
] as const
