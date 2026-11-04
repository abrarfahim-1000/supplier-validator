"""Stable UI stage and callback labels shared by the graph and job API."""

STAGE_INGESTION = "Document Ingestion"
STAGE_EXTRACTION = "Information Extraction"
STAGE_COMPARISON = "Purchase Request Comparison"
STAGE_RULES = "Company Rule Validation"
STAGE_DECISION = "Decision Generation"
STAGES = (
    STAGE_INGESTION,
    STAGE_EXTRACTION,
    STAGE_COMPARISON,
    STAGE_RULES,
    STAGE_DECISION,
)

STAGE_PROCESSING = "processing"
STAGE_COMPLETED = "completed"
STAGE_FAILED = "failed"
