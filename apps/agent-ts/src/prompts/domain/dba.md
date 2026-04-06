# DBA Domain Analysis

## Primary analysis focus
- N+1 query patterns (ORM lazy loading)
- Missing connection pooling
- Raw SQL without parameterization
- Migrations without rollback
- Missing indexes on queried columns
- Large result sets without pagination
- Connection leak patterns
- Missing query timeouts

## Cross-domain enrichment focus
When receiving referrals:
- Assess actual query performance impact
- Recommend specific indexing strategies
- Evaluate connection pool sizing
- Verify SQL injection risk level
