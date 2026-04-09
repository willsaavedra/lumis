"""
Demo data seeder for Lumis local development.
Creates realistic tenant, repos, analyses, findings, and billing events.
Does NOT make real API calls to GitHub, Stripe, or Datadog.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import structlog

log = structlog.get_logger(__name__)

NOW = datetime.now(timezone.utc)


async def seed() -> None:
    import sys
    sys.path.insert(0, "/workspace")

    from apps.api.core.config import settings
    from apps.api.core.database import AsyncSessionFactory
    from apps.api.core.security import hash_password, hash_api_key
    from apps.api.models.auth import Tenant, Organization, User, ApiKey
    from apps.api.models.scm import ScmConnection, Repository
    from apps.api.models.analysis import AnalysisJob, AnalysisResult, Finding
    from apps.api.models.billing import BillingEvent
    from apps.api.models.tag_system import TagDefinition, RepoTag, AnalysisTag
    from sqlalchemy import text

    async with AsyncSessionFactory() as session:
        # Bypass RLS for seeding
        await session.execute(text("SET LOCAL app.tenant_id = '00000000-0000-0000-0000-000000000000'"))

        # ── Tenant ────────────────────────────────────────────────────────────
        tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

        existing = await session.get(Tenant, tenant_id)
        if existing:
            print("Seed data already exists. Run `make clean` first to re-seed.")
            return

        tenant = Tenant(
            id=tenant_id,
            name="Acme Corp",
            slug="acme-corp",
            plan="growth",
            credits_remaining=653,
            credits_monthly_limit=1000,
            credits_used_this_period=347,
            onboarding_step=4,
            stripe_customer_id="cus_demo_acme",
            stripe_subscription_id="sub_demo_acme",
            stripe_subscription_status="active",
            stripe_current_period_end=NOW + timedelta(days=30),
            stripe_base_price_id="price_demo_growth_base",
            stripe_overage_price_id="price_demo_growth_overage",
            billing_email="billing@acme.com",
        )
        session.add(tenant)

        # ── Organization ──────────────────────────────────────────────────────
        org_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
        org = Organization(
            id=org_id,
            tenant_id=tenant_id,
            name="Acme Corp",
            scm_type="github",
        )
        session.add(org)

        # ── Users ─────────────────────────────────────────────────────────────
        owner_id = uuid.UUID("33333333-3333-3333-3333-333333333333")
        owner = User(
            id=owner_id,
            tenant_id=tenant_id,
            org_id=org_id,
            email="owner@acme.com",
            password_hash=hash_password("demo1234"),
            role="owner",
        )
        session.add(owner)

        dev_id = uuid.UUID("44444444-4444-4444-4444-444444444444")
        dev = User(
            id=dev_id,
            tenant_id=tenant_id,
            org_id=org_id,
            email="dev@acme.com",
            password_hash=hash_password("demo1234"),
            role="member",
        )
        session.add(dev)

        # ── API Key ───────────────────────────────────────────────────────────
        raw_key = "lumis_demo_" + "x9k2" * 8  # fake key ending in x9k2
        key_hash = hash_api_key(raw_key)
        api_key_obj = ApiKey(
            id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
            tenant_id=tenant_id,
            user_id=owner_id,
            key_hash=key_hash,
            key_hint="x9k2",
            label="Default",
            scope=["*"],
        )
        session.add(api_key_obj)

        # ── SCM Connection ────────────────────────────────────────────────────
        conn_id = uuid.UUID("66666666-6666-6666-6666-666666666666")
        conn = ScmConnection(
            id=conn_id,
            tenant_id=tenant_id,
            org_id=org_id,
            scm_type="github",
            installation_id="12345678",
            org_login="acme-corp",
            org_avatar_url="https://avatars.githubusercontent.com/u/12345678",
        )
        session.add(conn)

        # ── Repositories ──────────────────────────────────────────────────────
        repos = [
            {
                "id": uuid.UUID("77777777-7777-7777-7777-777777777771"),
                "scm_repo_id": "111111111",
                "full_name": "acme-corp/checkout-api",
                "default_branch": "main",
                "clone_url": "https://github.com/acme-corp/checkout-api.git",
                "schedule_enabled": True,
                "schedule_cron": "0 8 * * 1",
            },
            {
                "id": uuid.UUID("77777777-7777-7777-7777-777777777772"),
                "scm_repo_id": "111111112",
                "full_name": "acme-corp/inventory-service",
                "default_branch": "main",
                "clone_url": "https://github.com/acme-corp/inventory-service.git",
                "schedule_enabled": False,
            },
            {
                "id": uuid.UUID("77777777-7777-7777-7777-777777777773"),
                "scm_repo_id": "111111113",
                "full_name": "acme-corp/notification-worker",
                "default_branch": "main",
                "clone_url": "https://github.com/acme-corp/notification-worker.git",
                "schedule_enabled": False,
            },
            {
                "id": uuid.UUID("77777777-7777-7777-7777-777777777774"),
                "scm_repo_id": "111111114",
                "full_name": "acme-corp/auth-gateway",
                "default_branch": "main",
                "clone_url": "https://github.com/acme-corp/auth-gateway.git",
                "schedule_enabled": True,
                "schedule_cron": "0 9 * * 1",
            },
            {
                "id": uuid.UUID("77777777-7777-7777-7777-777777777775"),
                "scm_repo_id": "111111115",
                "full_name": "acme-corp/analytics-pipeline",
                "default_branch": "main",
                "clone_url": "https://github.com/acme-corp/analytics-pipeline.git",
                "schedule_enabled": False,
            },
        ]

        repo_objs = []
        for r in repos:
            schedule_enabled = r.pop("schedule_enabled", False)
            schedule_cron = r.pop("schedule_cron", "0 8 * * 1")
            repo = Repository(
                **r,
                tenant_id=tenant_id,
                org_id=org_id,
                scm_connection_id=conn_id,
                is_active=True,
                schedule_enabled=schedule_enabled,
                schedule_cron=schedule_cron,
            )
            session.add(repo)
            repo_objs.append(repo)

        await session.flush()

        # ── Analysis Jobs & Results ───────────────────────────────────────────
        checkout_repo_id = uuid.UUID("77777777-7777-7777-7777-777777777771")
        inventory_repo_id = uuid.UUID("77777777-7777-7777-7777-777777777772")
        notification_repo_id = uuid.UUID("77777777-7777-7777-7777-777777777773")
        auth_repo_id = uuid.UUID("77777777-7777-7777-7777-777777777774")
        analytics_repo_id = uuid.UUID("77777777-7777-7777-7777-777777777775")

        jobs_data = [
            {
                "repo_id": checkout_repo_id,
                "trigger": "pr",
                "pr_number": 142,
                "commit_sha": "a1b2c3d4e5f6a1b2c3d4",
                "analysis_type": "full",
                "credits_consumed": 3,
                "score_global": 67,
                "score_metrics": 72,
                "score_logs": 55,
                "score_traces": 74,
                "findings_data": [
                    {
                        "pillar": "logs",
                        "severity": "critical",
                        "dimension": "snr",
                        "title": "Debug logging inside hot loop",
                        "description": "log.Debug() called inside a for-range loop over orders. This generates thousands of log entries per request and will flood your log aggregator.",
                        "file_path": "internal/checkout/processor.go",
                        "line_start": 87,
                        "line_end": 95,
                        "suggestion": 'slog.Info("batch_processed", "count", len(orders), "duration_ms", elapsed.Milliseconds())',
                        "estimated_monthly_cost_impact": 210.0,
                    },
                    {
                        "pillar": "traces",
                        "severity": "warning",
                        "dimension": "cost",
                        "title": "Missing sampler configuration",
                        "description": "Tracing is configured without a sampler, defaulting to 100% trace collection. At current traffic this will cost ~$180/month in storage.",
                        "file_path": "cmd/server/main.go",
                        "line_start": 23,
                        "line_end": 28,
                        "suggestion": 'tracerProvider := sdktrace.NewTracerProvider(\n    sdktrace.WithSampler(sdktrace.ParentBased(sdktrace.TraceIDRatioBased(0.1))),\n)',
                        "estimated_monthly_cost_impact": 180.0,
                    },
                ],
                "created_at": NOW - timedelta(days=2, hours=3),
            },
            {
                "repo_id": inventory_repo_id,
                "trigger": "pr",
                "pr_number": 89,
                "commit_sha": "b2c3d4e5f6a1b2c3d4e5",
                "analysis_type": "full",
                "credits_consumed": 3,
                "score_global": 81,
                "score_metrics": 68,
                "score_logs": 88,
                "score_traces": 87,
                "findings_data": [
                    {
                        "pillar": "metrics",
                        "severity": "warning",
                        "dimension": "coverage",
                        "title": "Missing RED pattern for critical endpoint",
                        "description": "The /api/inventory/reserve endpoint handles stock reservations but has no Rate, Error, or Duration metrics. This is a business-critical path.",
                        "file_path": "app/api/inventory.py",
                        "line_start": 45,
                        "line_end": 65,
                        "suggestion": "inventory_reservations = meter.create_counter('inventory.reservations', description='Stock reservation attempts')\ninventory_errors = meter.create_counter('inventory.reservation_errors')\ninventory_duration = meter.create_histogram('inventory.reservation_duration_ms')",
                        "estimated_monthly_cost_impact": 0.0,
                    },
                    {
                        "pillar": "metrics",
                        "severity": "info",
                        "dimension": "compliance",
                        "title": "Missing mandatory team tag",
                        "description": "Metrics emitted by this service are missing the required 'team' tag per internal standards.",
                        "file_path": "app/telemetry.py",
                        "line_start": 12,
                        "line_end": 20,
                        "suggestion": 'resource = Resource({"service.name": "inventory-service", "team": "platform", "cost-center": "eng-platform"})',
                        "estimated_monthly_cost_impact": 0.0,
                    },
                ],
                "created_at": NOW - timedelta(days=4, hours=1),
            },
            {
                "repo_id": notification_repo_id,
                "trigger": "manual",
                "pr_number": None,
                "commit_sha": "c3d4e5f6a1b2c3d4e5f6",
                "analysis_type": "full",
                "credits_consumed": 3,
                "score_global": 44,
                "score_metrics": 20,
                "score_logs": 50,
                "score_traces": 62,
                "findings_data": [
                    {
                        "pillar": "traces",
                        "severity": "critical",
                        "dimension": "coverage",
                        "title": "No OTel instrumentation detected",
                        "description": "The notification worker has no OpenTelemetry SDK configured. No traces, metrics, or structured logs are being emitted.",
                        "file_path": "src/worker.ts",
                        "line_start": 1,
                        "line_end": 30,
                        "suggestion": "npm install @opentelemetry/sdk-node @opentelemetry/auto-instrumentations-node\n// Add to src/tracing.ts:\nimport { NodeSDK } from '@opentelemetry/sdk-node';\nimport { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';\nconst sdk = new NodeSDK({ instrumentations: [getNodeAutoInstrumentations()] });\nsdk.start();",
                        "estimated_monthly_cost_impact": 0.0,
                    },
                    {
                        "pillar": "logs",
                        "severity": "critical",
                        "dimension": "snr",
                        "title": "console.log used throughout codebase",
                        "description": "47 instances of console.log detected. These cannot be queried, sampled, or correlated with traces.",
                        "file_path": "src/handlers/email.ts",
                        "line_start": 34,
                        "line_end": 34,
                        "suggestion": "// Replace: console.log(`Sending email to ${address}`)\n// With:\nimport pino from 'pino';\nconst logger = pino();\nlogger.info({ recipient_type: 'user', channel: 'email' }, 'notification_sent');",
                        "estimated_monthly_cost_impact": 0.0,
                    },
                ],
                "created_at": NOW - timedelta(days=7, hours=2),
            },
            {
                "repo_id": checkout_repo_id,
                "trigger": "pr",
                "pr_number": 138,
                "commit_sha": "d4e5f6a1b2c3d4e5f6a1",
                "analysis_type": "quick",
                "credits_consumed": 1,
                "score_global": 72,
                "score_metrics": 78,
                "score_logs": 71,
                "score_traces": 67,
                "findings_data": [
                    {
                        "pillar": "iac",
                        "severity": "warning",
                        "dimension": "coverage",
                        "title": "SQS queue without CloudWatch alarm",
                        "description": "aws_sqs_queue.order_events has no CloudWatch alarm for queue depth or oldest message age. Silent failures will go undetected.",
                        "file_path": "infra/sqs.tf",
                        "line_start": 12,
                        "line_end": 25,
                        "suggestion": 'resource "aws_cloudwatch_metric_alarm" "order_queue_depth" {\n  alarm_name  = "order-events-depth"\n  metric_name = "ApproximateNumberOfMessagesVisible"\n  namespace   = "AWS/SQS"\n  statistic   = "Average"\n  period      = 300\n  threshold   = 1000\n  comparison_operator = "GreaterThanThreshold"\n}',
                        "estimated_monthly_cost_impact": 0.0,
                    },
                ],
                "created_at": NOW - timedelta(days=10),
            },
            {
                "repo_id": inventory_repo_id,
                "trigger": "scheduled",
                "pr_number": None,
                "commit_sha": "e5f6a1b2c3d4e5f6a1b2",
                "analysis_type": "full",
                "credits_consumed": 3,
                "score_global": 88,
                "score_metrics": 85,
                "score_logs": 91,
                "score_traces": 88,
                "findings_data": [
                    {
                        "pillar": "metrics",
                        "severity": "info",
                        "dimension": "compliance",
                        "title": "SDK version is outdated",
                        "description": "opentelemetry-sdk 1.18.0 is being used. Latest is 1.27.0. Update for improved sampling controls and OTLP improvements.",
                        "file_path": "requirements.txt",
                        "line_start": 5,
                        "line_end": 5,
                        "suggestion": "opentelemetry-sdk==1.27.0\nopentelemetry-exporter-otlp-proto-grpc==1.27.0",
                        "estimated_monthly_cost_impact": 0.0,
                    },
                ],
                "created_at": NOW - timedelta(days=14),
            },
            {
                "repo_id": auth_repo_id,
                "trigger": "pr",
                "pr_number": 31,
                "commit_sha": "f6a1b2c3d4e5f6a1b2c3",
                "analysis_type": "full",
                "credits_consumed": 3,
                "score_global": 73,
                "score_metrics": 70,
                "score_logs": 80,
                "score_traces": 69,
                "findings_data": [
                    {
                        "pillar": "traces",
                        "severity": "warning",
                        "dimension": "coverage",
                        "title": "Missing span on auth middleware",
                        "description": "The JWT validation middleware processes every request but has no trace span. Auth latency is invisible in distributed traces.",
                        "file_path": "cmd/gateway/middleware.go",
                        "line_start": 45,
                        "line_end": 62,
                        "suggestion": 'ctx, span := otel.Tracer("auth").Start(ctx, "jwt.validate")\ndefer span.End()',
                        "estimated_monthly_cost_impact": 0.0,
                    },
                    {
                        "pillar": "metrics",
                        "severity": "critical",
                        "dimension": "cost",
                        "title": "Unbounded cardinality on user_id label",
                        "description": "auth_requests_total metric uses user_id as a label, creating potentially millions of time series.",
                        "file_path": "internal/metrics/auth.go",
                        "line_start": 18,
                        "line_end": 25,
                        "suggestion": 'Remove user_id from label set. Use exemplars or log correlation instead.',
                        "estimated_monthly_cost_impact": 320.0,
                    },
                ],
                "created_at": NOW - timedelta(days=1, hours=5),
            },
            {
                "repo_id": analytics_repo_id,
                "trigger": "manual",
                "pr_number": None,
                "commit_sha": "a1b2c3d4e5f6a7b8c9d0",
                "analysis_type": "full",
                "credits_consumed": 3,
                "score_global": 55,
                "score_metrics": 40,
                "score_logs": 65,
                "score_traces": 60,
                "findings_data": [
                    {
                        "pillar": "logs",
                        "severity": "warning",
                        "dimension": "snr",
                        "title": "Noisy Spark executor logs",
                        "description": "Spark executors emit DEBUG-level logs for every partition processed. At 50k partitions/day, this generates ~4GB of unstructured logs.",
                        "file_path": "src/main/scala/Pipeline.scala",
                        "line_start": 120,
                        "line_end": 135,
                        "suggestion": "Set log level to WARN for org.apache.spark.executor and add structured job-level logging instead.",
                        "estimated_monthly_cost_impact": 150.0,
                    },
                    {
                        "pillar": "metrics",
                        "severity": "critical",
                        "dimension": "coverage",
                        "title": "No pipeline throughput metrics",
                        "description": "The analytics pipeline has no metrics for records processed, pipeline latency, or error rates. SLA compliance is unmeasurable.",
                        "file_path": "src/main/scala/Pipeline.scala",
                        "line_start": 1,
                        "line_end": 15,
                        "suggestion": "Add Micrometer counters: pipeline.records.processed, pipeline.batch.duration, pipeline.errors",
                        "estimated_monthly_cost_impact": 0.0,
                    },
                ],
                "created_at": NOW - timedelta(days=3, hours=2),
            },
        ]

        for i, job_data in enumerate(jobs_data):
            job_id = uuid.uuid4()
            findings_data = job_data.pop("findings_data")
            created_at = job_data.pop("created_at")
            score_global = job_data.pop("score_global")
            score_metrics = job_data.pop("score_metrics")
            score_logs = job_data.pop("score_logs")
            score_traces = job_data.pop("score_traces")

            job = AnalysisJob(
                id=job_id,
                tenant_id=tenant_id,
                status="completed",
                branch_ref="main",
                credits_reserved=job_data.get("credits_consumed", 3),
                started_at=created_at + timedelta(minutes=2),
                completed_at=created_at + timedelta(minutes=5),
                created_at=created_at,
                **job_data,
            )
            session.add(job)
            await session.flush()

            result = AnalysisResult(
                job_id=job_id,
                tenant_id=tenant_id,
                score_global=score_global,
                score_metrics=score_metrics,
                score_logs=score_logs,
                score_traces=score_traces,
                score_cost=max(0, score_global - 10),
                score_snr=min(100, score_global + 5),
                score_pipeline=min(100, score_global + 10),
                score_compliance=min(100, score_global + 8),
                findings=findings_data,
                raw_llm_calls=4,
                input_tokens_total=12000,
                output_tokens_total=3500,
                cost_usd=0.18,
            )
            session.add(result)
            await session.flush()

            for f in findings_data:
                finding = Finding(
                    result_id=result.id,
                    tenant_id=tenant_id,
                    **f,
                )
                session.add(finding)

            # Billing event for this job
            session.add(BillingEvent(
                tenant_id=tenant_id,
                job_id=job_id,
                event_type="consumed",
                credits_delta=-job_data.get("credits_consumed", 3),
                description=f"Analysis completed: {job_data.get('analysis_type')} on {job_data.get('commit_sha', '')[:8]}",
                created_at=job.completed_at,
            ))

        # Billing event for period renewal
        session.add(BillingEvent(
            tenant_id=tenant_id,
            event_type="period_renewed",
            credits_delta=1000,
            usd_amount=149.00,
            description="Monthly billing period renewed — Growth plan",
            created_at=NOW - timedelta(days=1),
        ))

        # ── Tag Definitions ────────────────────────────────────────────────
        _tag_defs = [
            {"key": "team", "label": "Squad / Team", "description": "Which team owns this repository", "required": True, "allowed_values": None, "color_class": "tag-team", "sort_order": 1},
            {"key": "env", "label": "Environment", "description": "Deployment environment", "required": True, "allowed_values": ["production", "staging", "dev", "sandbox"], "color_class": "tag-env", "sort_order": 2},
            {"key": "criticality", "label": "Business Criticality", "description": "How critical this service is", "required": True, "allowed_values": ["critical", "high", "medium", "low"], "color_class": "tag-criticality", "sort_order": 3},
            {"key": "domain", "label": "Business Domain", "description": "Business domain", "required": False, "allowed_values": None, "color_class": "tag-domain", "sort_order": 4},
            {"key": "cost-center", "label": "Cost Center", "description": "Cost allocation center", "required": False, "allowed_values": None, "color_class": "tag-cost-center", "sort_order": 5},
            {"key": "lang", "label": "Language", "description": "Primary programming language", "required": False, "allowed_values": ["go", "python", "java", "node", "typescript", "ruby", "rust"], "color_class": "tag-service", "sort_order": 6},
        ]
        for td in _tag_defs:
            session.add(TagDefinition(tenant_id=tenant_id, **td))
        await session.flush()

        # ── Repo Tags ──────────────────────────────────────────────────────
        _repo_tags = {
            checkout_repo_id: [
                ("team", "payments", "user"),
                ("env", "production", "user"),
                ("criticality", "critical", "user"),
                ("domain", "commerce", "user"),
                ("cost-center", "eng-payments", "user"),
                ("lang", "go", "auto"),
            ],
            inventory_repo_id: [
                ("team", "platform", "user"),
                ("env", "production", "user"),
                ("criticality", "high", "user"),
                ("domain", "supply-chain", "user"),
                ("lang", "python", "auto"),
            ],
            notification_repo_id: [
                ("team", "platform", "user"),
                ("env", "staging", "user"),
                ("criticality", "medium", "user"),
                ("domain", "communications", "user"),
                ("lang", "typescript", "auto"),
            ],
            auth_repo_id: [
                ("team", "security", "user"),
                ("env", "production", "user"),
                ("criticality", "critical", "user"),
                ("domain", "identity", "user"),
                ("cost-center", "eng-security", "user"),
                ("lang", "go", "auto"),
            ],
            analytics_repo_id: [
                ("team", "data", "user"),
                ("env", "production", "user"),
                ("criticality", "high", "user"),
                ("domain", "analytics", "user"),
                ("cost-center", "eng-data", "user"),
                ("lang", "java", "auto"),
            ],
        }
        for rid, tag_list in _repo_tags.items():
            for key, value, source in tag_list:
                session.add(RepoTag(tenant_id=tenant_id, repo_id=rid, key=key, value=value, source=source))
        await session.flush()

        # ── Analysis Tags (snapshot for each job) ──────────────────────────
        _system_tags_by_job: dict[int, list[tuple[str, str]]] = {
            0: [("trigger", "pr"), ("branch", "main"), ("type", "full"), ("pr", "142")],
            1: [("trigger", "pr"), ("branch", "main"), ("type", "full"), ("pr", "89")],
            2: [("trigger", "manual"), ("branch", "main"), ("type", "full")],
            3: [("trigger", "pr"), ("branch", "main"), ("type", "quick"), ("pr", "138")],
            4: [("trigger", "scheduled"), ("branch", "main"), ("type", "full")],
            5: [("trigger", "pr"), ("branch", "main"), ("type", "full"), ("pr", "31")],
            6: [("trigger", "manual"), ("branch", "main"), ("type", "full")],
        }
        _repo_for_job = [
            checkout_repo_id, inventory_repo_id, notification_repo_id,
            checkout_repo_id, inventory_repo_id,
            auth_repo_id, analytics_repo_id,
        ]

        all_jobs_result = await session.execute(
            text("SELECT id, repo_id FROM analysis_jobs WHERE tenant_id = :tid ORDER BY created_at"),
            {"tid": str(tenant_id)},
        )
        all_jobs = all_jobs_result.fetchall()

        for idx, (jid, repo_id_raw) in enumerate(all_jobs):
            repo_id_val = uuid.UUID(str(repo_id_raw)) if not isinstance(repo_id_raw, uuid.UUID) else repo_id_raw
            job_uuid = uuid.UUID(str(jid)) if not isinstance(jid, uuid.UUID) else jid
            repo_tag_list = _repo_tags.get(repo_id_val, [])
            for key, value, source in repo_tag_list:
                session.add(AnalysisTag(tenant_id=tenant_id, job_id=job_uuid, key=key, value=value, source=source))
            sys_tags = _system_tags_by_job.get(idx, [])
            for key, value in sys_tags:
                session.add(AnalysisTag(tenant_id=tenant_id, job_id=job_uuid, key=key, value=value, source="system"))
        await session.flush()

        await session.commit()
        print("✓ Seed complete!")
        print("  Tenant:   Acme Corp (plan=growth, 653 credits remaining)")
        print("  Login:    owner@acme.com / demo1234")
        print("  Repos:    5 active (checkout-api, inventory-service, notification-worker, auth-gateway, analytics-pipeline)")
        print("  Analyses: 7 completed (scores: 67, 81, 44, 72, 88, 73, 55)")
        print("  Tags:     6 definitions, repo_tags + analysis_tags seeded")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "/workspace")
    asyncio.run(seed())
