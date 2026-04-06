# Security Domain Analysis

## Primary analysis focus
- PII in log output (emails, tokens, passwords, API keys, SSNs)
- Hardcoded secrets and credentials
- SQL injection patterns
- Missing input validation
- Authentication/authorization gaps
- CORS misconfiguration
- Insecure cryptographic practices
- Missing audit logging for sensitive operations

## Cross-domain enrichment focus
When receiving referrals from other agents:
- Validate whether flagged data is actually PII
- Assess GDPR/CCPA/OWASP implications
- Classify severity based on exposure risk
- Suggest specific remediation (redaction, hashing, vault)
