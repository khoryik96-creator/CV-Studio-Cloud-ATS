# DeepSeek and uploaded CV processing

Fixed HTTPS endpoint for DeepSeek Chat Completions, no redirects, retries, custom endpoint or real credential configuration. Uses non-streaming JSON output, records reported token usage even for truncated replies; unknown provider outcomes keep their reservation. Costs remain calculated using configured conservative rates, not verified provider invoices. Socket timeout is not a total request deadline. Production requires an outer worker deadline and heartbeat, model catalog and approved prices.

Adds bounded text/DOCX/PDF extraction with source DOCX bullet levels, table order, file integrity verification, and internal job execution using the existing budgeted completion and CV rendering. Image-only/empty PDF pages are refused pending OCR. Text-bearing PDF pages can still omit image text; PDF completeness must be reviewed. No malware scanner, parser sandbox, continuous heartbeat or durable output publication yet. Job execution returns bytes and never marks a job successful before output persistence. No routes, scheduler, real paid requests or production deployment. Tests use fake HTTP and synthetic documents.

## Review fixes
Recheck durable job metadata before reading bytes, including module and document ID. Avoid masking a billed completion with a socket close error. Test worker ownership mismatch before document access and exercise the adapter with a fake transport. No successful job state is written by this adapter; durable publication is the next prerequisite.
