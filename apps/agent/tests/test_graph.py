"""Agent graph tests."""
import pytest
from opentelemetry import context
from apps.agent.schemas import AgentState


def test_agent_state_structure() -> None:
    """Verify AgentState TypedDict has required keys."""
    state: AgentState = {
        "job_id": "test-123",
        "tenant_id": "tenant-456",
        "request": {},
        "repo_path": None,
        "changed_files": [],
        "call_graph": None,
        "coverage_map": None,
        "dd_coverage": None,
        "findings": [],
        "efficiency_scores": {},
        "token_usage": {},
        "messages": [],
        "error": None,
        "stage": "starting",
        "progress_pct": 0,
    }
    assert state["job_id"] == "test-123"


@pytest.mark.asyncio
async def test_pre_triage_irrelevant_files() -> None:
    from apps.agent.nodes.pre_triage import _quick_classify
    
    # Copy current trace context for async task execution
    ctx = context.copy_context()
    
    # Execute classification with trace context propagation
    def run_with_context():
        assert _quick_classify("README.md") == 0
        assert _quick_classify("main.go") == 1
        assert _quick_classify("handler_test.go") == 0
        assert _quick_classify("service.py") == 1
    
    await asyncio.get_event_loop().run_in_executor(None, ctx.run, run_with_context)