#!/usr/bin/env python3.12
"""
Tests E2E para Phase C (v4-C1..C5) de architect-cli.

Cubre con mocks de agent_factory (sin necesidad de LLM real):
- C1: Ralph Loop con múltiples checks que fallan y se corrigen
- C2: Parallel execution (unidades + worktree logic)
- C3: Pipeline con checks, condition, output_var, checkpoint
- C5: Auto-review E2E

Uso:
    python3.12 scripts/test_phase_c_e2e.py
"""

import os
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Helpers ─────────────────────────────────────────────────────────────

_passed = 0
_failed = 0
_errors = []
_section = ""


def section(name: str) -> None:
    global _section
    _section = name
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


def ok(name: str, detail: str = "") -> None:
    global _passed
    _passed += 1
    d = f" — {detail}" if detail else ""
    print(f"  ✓ {name}{d}")


def fail(name: str, detail: str = "") -> None:
    global _failed
    _failed += 1
    d = f" — {detail}" if detail else ""
    print(f"  ✗ {name}{d}")
    _errors.append(f"[{_section}] {name}: {detail}")


# ── Mock helpers ────────────────────────────────────────────────────────


class MockCostTracker:
    def __init__(self, cost=0.01):
        self.total_cost_usd = cost


class MockAgentState:
    def __init__(self, final_output="", status="success", steps=3, cost=0.01):
        self.final_output = final_output
        self.status = status
        self.current_step = steps
        self.cost_tracker = MockCostTracker(cost) if cost > 0 else None


class MockAgent:
    def __init__(self, state=None):
        self.state = state or MockAgentState()
        self.run_calls = []

    def run(self, prompt):
        self.run_calls.append(prompt)
        return self.state


# ══════════════════════════════════════════════════════════════════════════
# C1: RALPH LOOP E2E
# ══════════════════════════════════════════════════════════════════════════

def test_ralph_loop_e2e():
    """Tests E2E del Ralph Loop con múltiples checks."""
    section("C1. RALPH LOOP — Múltiples checks, fallos y correcciones")

    from architect.features.ralph import RalphConfig, RalphLoop

    # Test C1.1: Múltiples checks, algunos fallan, luego todos pasan
    try:
        workspace = Path(tempfile.mkdtemp(prefix="ralph_e2e_"))

        # Simular 2 checks: pytest y ruff. Iter 1: ambos fallan. Iter 2: pytest pasa, ruff falla. Iter 3: ambos pasan.
        subprocess_call_count = 0

        def mock_subprocess(*args, **kwargs):
            nonlocal subprocess_call_count
            subprocess_call_count += 1
            cmd = args[0] if args else kwargs.get("args", [])

            # git rev-parse HEAD
            if isinstance(cmd, list) and "rev-parse" in cmd:
                return MagicMock(stdout="abc123\n", returncode=0)
            # git diff
            if isinstance(cmd, list) and "diff" in cmd:
                return MagicMock(stdout="diff --git a/file.py\n+fixed", returncode=0)
            # shell checks
            if kwargs.get("shell"):
                check_cmd = args[0]
                # Track by command type to simulate different check results
                if "pytest" in check_cmd:
                    # iter 1: fail, iter 2+: pass
                    pytest_calls = sum(
                        1 for i in range(subprocess_call_count)
                        if i > 0  # rough heuristic
                    )
                    # Simple: alternate based on total call count
                    return MagicMock(stdout="OK", returncode=0)
                elif "ruff" in check_cmd:
                    return MagicMock(stdout="OK", returncode=0)
                else:
                    return MagicMock(stdout="OK", returncode=0)

            return MagicMock(stdout="", returncode=0)

        # Use a sequence-based approach for predictable behavior
        check_sequences = {
            "pytest": iter([1, 0, 0]),  # fail, pass, pass
            "ruff": iter([1, 1, 0]),    # fail, fail, pass
        }

        def subprocess_sequenced(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "rev-parse" in cmd:
                return MagicMock(stdout="abc123\n", returncode=0)
            if isinstance(cmd, list) and "diff" in cmd:
                return MagicMock(stdout="diff +fix", returncode=0)
            if kwargs.get("shell"):
                check_cmd = args[0]
                for key, seq in check_sequences.items():
                    if key in check_cmd:
                        try:
                            rc = next(seq)
                        except StopIteration:
                            rc = 0
                        output = "FAIL" if rc != 0 else "OK"
                        return MagicMock(stdout=output, stderr="" if rc == 0 else "error", returncode=rc)
                return MagicMock(stdout="OK", returncode=0)
            return MagicMock(stdout="", returncode=0)

        iter_count = 0

        def factory(**kwargs):
            nonlocal iter_count
            iter_count += 1
            if iter_count < 3:
                return MockAgent(MockAgentState(final_output="Working on it", steps=4, cost=0.02))
            return MockAgent(MockAgentState(final_output="All done. COMPLETE", steps=6, cost=0.03))

        config = RalphConfig(
            task="Fix the test suite and linting errors",
            checks=["pytest tests/", "ruff check src/"],
            max_iterations=10,
        )

        with patch("architect.features.ralph.subprocess.run", side_effect=subprocess_sequenced):
            loop = RalphLoop(config=config, agent_factory=factory, workspace_root=str(workspace))
            result = loop.run()

        assert result.success, f"Expected success, got stop_reason={result.stop_reason}"
        assert result.total_iterations == 3, f"Expected 3 iterations, got {result.total_iterations}"
        assert result.stop_reason == "all_checks_passed"
        assert result.total_cost > 0

        # Verify progress file was created
        progress = workspace / ".architect" / "ralph-progress.md"
        assert progress.exists(), "Progress file not created"
        content = progress.read_text()
        assert "Failed" in content, "No failed iterations in progress"
        assert "Passed" in content, "No passed iteration in progress"

        ok("C1.1 Multi-check fail→fix", f"iters={result.total_iterations}, cost=${result.total_cost:.4f}")
    except Exception as e:
        fail("C1.1 Multi-check fail→fix", str(e))

    # Test C1.2: Budget exhausted stops the loop
    try:
        workspace2 = Path(tempfile.mkdtemp(prefix="ralph_budget_"))

        def factory_expensive(**kwargs):
            return MockAgent(MockAgentState(final_output="trying", steps=5, cost=0.10))

        config2 = RalphConfig(
            task="Fix everything",
            checks=["false"],
            max_iterations=100,
            max_cost=0.20,
        )

        with patch("architect.features.ralph.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(stdout="FAIL", returncode=1)
            loop2 = RalphLoop(config=config2, agent_factory=factory_expensive, workspace_root=str(workspace2))
            result2 = loop2.run()

        assert not result2.success
        assert result2.stop_reason == "budget_exhausted"
        assert result2.total_iterations == 2  # 0.10 + 0.10 = 0.20, 3rd blocked

        ok("C1.2 Budget exhausted", f"iters={result2.total_iterations}, reason={result2.stop_reason}")
    except Exception as e:
        fail("C1.2 Budget exhausted", str(e))

    # Test C1.3: Workspace_root passed to factory (worktree fix verification)
    try:
        workspace3 = Path(tempfile.mkdtemp(prefix="ralph_ws_"))
        factory_kwargs = []

        def factory_capture(**kwargs):
            factory_kwargs.append(kwargs)
            return MockAgent(MockAgentState(final_output="COMPLETE", steps=3, cost=0.01))

        config3 = RalphConfig(task="Test", checks=["echo ok"])

        with patch("architect.features.ralph.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(stdout="abc123\nOK\n", returncode=0)
            loop3 = RalphLoop(config=config3, agent_factory=factory_capture, workspace_root=str(workspace3))
            loop3.run()

        assert len(factory_kwargs) >= 1
        assert factory_kwargs[0].get("workspace_root") == str(workspace3), \
            f"workspace_root not passed: {factory_kwargs[0]}"

        ok("C1.3 Factory receives workspace_root", f"ws={factory_kwargs[0]['workspace_root']}")
    except Exception as e:
        fail("C1.3 Factory receives workspace_root", str(e))

    # Test C1.4: Clean context per iteration (each iteration gets fresh prompt)
    try:
        workspace4 = Path(tempfile.mkdtemp(prefix="ralph_ctx_"))
        prompts_received = []

        def factory_capture_prompt(**kwargs):
            agent = MockAgent(MockAgentState(final_output="COMPLETE", steps=2, cost=0.01))
            original_run = agent.run

            def capturing_run(prompt):
                prompts_received.append(prompt)
                return original_run(prompt)

            agent.run = capturing_run
            return agent

        # Simulate 2 iterations: first fails, second passes
        check_iter = iter([1, 0])

        def subprocess_check(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            if isinstance(cmd, list) and "rev-parse" in cmd:
                return MagicMock(stdout="abc123\n", returncode=0)
            if isinstance(cmd, list) and "diff" in cmd:
                return MagicMock(stdout="diff +change", returncode=0)
            if kwargs.get("shell"):
                try:
                    rc = next(check_iter)
                except StopIteration:
                    rc = 0
                return MagicMock(stdout="FAIL" if rc else "OK", stderr="err" if rc else "", returncode=rc)
            return MagicMock(stdout="", returncode=0)

        config4 = RalphConfig(task="Fix bug X", checks=["pytest"])

        with patch("architect.features.ralph.subprocess.run", side_effect=subprocess_check):
            loop4 = RalphLoop(config=config4, agent_factory=factory_capture_prompt, workspace_root=str(workspace4))
            loop4.run()

        assert len(prompts_received) == 2, f"Expected 2 prompts, got {len(prompts_received)}"
        # Second prompt should contain error info from first iteration
        assert "Error" in prompts_received[1] or "iteraci" in prompts_received[1].lower()
        # Second prompt should still contain the original task
        assert "Fix bug X" in prompts_received[1]

        ok("C1.4 Clean context per iteration", f"prompts={len(prompts_received)}")
    except Exception as e:
        fail("C1.4 Clean context per iteration", str(e))


# ══════════════════════════════════════════════════════════════════════════
# C2: PARALLEL EXECUTION
# ══════════════════════════════════════════════════════════════════════════

def test_parallel_e2e():
    """Tests E2E de ejecución paralela."""
    section("C2. PARALLEL EXECUTION — Worktree isolation y config")

    from architect.features.parallel import ParallelConfig, ParallelRunner, WorkerResult

    # Test C2.1: ParallelConfig con múltiples tareas
    try:
        config = ParallelConfig(
            tasks=["implement auth", "implement logging", "implement caching"],
            workers=3,
            models=["gpt-4o", "claude-sonnet-4-6", "deepseek-chat"],
            agent="build",
            budget_per_worker=0.50,
            timeout_per_worker=120,
        )

        assert len(config.tasks) == 3
        assert config.workers == 3
        assert config.models is not None
        assert len(config.models) == 3
        assert config.budget_per_worker == 0.50

        ok("C2.1 ParallelConfig", f"tasks={len(config.tasks)}, workers={config.workers}")
    except Exception as e:
        fail("C2.1 ParallelConfig", str(e))

    # Test C2.2: WorkerResult dataclass
    try:
        wr = WorkerResult(
            worker_id=0,
            branch="architect-parallel-0",
            model="gpt-4o",
            status="success",
            steps=15,
            cost=0.25,
            duration=45.0,
            files_modified=["auth.py", "tests/test_auth.py"],
            worktree_path="/tmp/wt-0",
        )

        assert wr.worker_id == 0
        assert wr.status == "success"
        assert len(wr.files_modified) == 2

        ok("C2.2 WorkerResult", f"worker={wr.worker_id}, status={wr.status}")
    except Exception as e:
        fail("C2.2 WorkerResult", str(e))

    # Test C2.3: ParallelRunner task/model assignment
    try:
        config = ParallelConfig(
            tasks=["task A", "task B"],
            workers=3,
            models=["model-1", "model-2", "model-3"],
        )
        runner = ParallelRunner(config, "/tmp/fake-workspace")

        # Test task round-robin
        assert runner._get_task_for_worker(0) == "task A"
        assert runner._get_task_for_worker(1) == "task B"
        assert runner._get_task_for_worker(2) == "task A"  # Wraps around

        # Test model assignment
        assert runner._get_model_for_worker(0) == "model-1"
        assert runner._get_model_for_worker(1) == "model-2"
        assert runner._get_model_for_worker(2) == "model-3"

        ok("C2.3 Task/model assignment", "Round-robin and model mapping correct")
    except Exception as e:
        fail("C2.3 Task/model assignment", str(e))

    # Test C2.4: Worktree naming convention
    try:
        from architect.features.parallel import WORKTREE_PREFIX
        assert WORKTREE_PREFIX == ".architect-parallel"

        config = ParallelConfig(tasks=["test"])
        runner = ParallelRunner(config, "/tmp/test-repo")

        # The branch naming should use the prefix
        ok("C2.4 Worktree naming", f"prefix={WORKTREE_PREFIX}")
    except Exception as e:
        fail("C2.4 Worktree naming", str(e))


# ══════════════════════════════════════════════════════════════════════════
# C3: PIPELINE E2E
# ══════════════════════════════════════════════════════════════════════════

def test_pipeline_e2e():
    """Tests E2E del Pipeline Mode."""
    section("C3. PIPELINE — Checks, conditions, output_var, checkpoints")

    from architect.features.pipelines import (
        PipelineConfig,
        PipelineRunner,
        PipelineStep,
        PipelineStepResult,
    )

    # Test C3.1: Pipeline con checks en un step
    try:
        workspace = Path(tempfile.mkdtemp(prefix="pipe_checks_"))

        steps = [
            PipelineStep(
                name="implement",
                agent="build",
                prompt="Implement feature X",
                checks=["echo 'check OK'"],
            ),
        ]
        config = PipelineConfig(name="test-checks", steps=steps)

        def factory(**kwargs):
            return MockAgent(MockAgentState(final_output="Done", status="success", cost=0.01))

        with patch("architect.features.pipelines.subprocess.run") as mock_sp:
            # For checks, return success
            mock_sp.return_value = MagicMock(stdout="check OK", stderr="", returncode=0)

            runner = PipelineRunner(config, factory, workspace_root=str(workspace))
            results = runner.run()

        assert len(results) == 1
        assert results[0].status == "success"
        assert results[0].checks_passed is True

        ok("C3.1 Pipeline checks pass", f"status={results[0].status}, checks_passed={results[0].checks_passed}")
    except Exception as e:
        fail("C3.1 Pipeline checks pass", str(e))

    # Test C3.2: Pipeline checks fail
    try:
        workspace = Path(tempfile.mkdtemp(prefix="pipe_checks_fail_"))

        steps = [
            PipelineStep(
                name="implement",
                agent="build",
                prompt="Implement feature",
                checks=["pytest tests/", "ruff check ."],
            ),
        ]
        config = PipelineConfig(name="test-checks-fail", steps=steps)

        check_results = iter([
            MagicMock(stdout="OK", returncode=0),      # pytest passes
            MagicMock(stdout="E501", returncode=1),     # ruff fails
        ])

        def factory(**kwargs):
            return MockAgent(MockAgentState(final_output="Done", status="success", cost=0.01))

        with patch("architect.features.pipelines.subprocess.run") as mock_sp:
            mock_sp.side_effect = lambda *a, **kw: next(check_results)
            runner = PipelineRunner(config, factory, workspace_root=str(workspace))
            results = runner.run()

        assert len(results) == 1
        assert results[0].checks_passed is False

        ok("C3.2 Pipeline checks fail", f"checks_passed={results[0].checks_passed}")
    except Exception as e:
        fail("C3.2 Pipeline checks fail", str(e))

    # Test C3.3: Pipeline condition — step skipped when condition is false
    try:
        workspace = Path(tempfile.mkdtemp(prefix="pipe_cond_"))

        steps = [
            PipelineStep(name="always", prompt="Always runs"),
            PipelineStep(name="conditional", prompt="Only if flag is true", condition="{{run_tests}}"),
            PipelineStep(name="also-always", prompt="Also always runs"),
        ]
        config = PipelineConfig(
            name="test-condition",
            steps=steps,
            variables={"run_tests": "false"},
        )

        factory_calls = []

        def factory(**kwargs):
            factory_calls.append(kwargs)
            return MockAgent(MockAgentState(final_output="Done", status="success", cost=0.01))

        runner = PipelineRunner(config, factory, workspace_root=str(workspace))
        results = runner.run()

        assert len(results) == 3
        assert results[0].status == "success"  # always
        assert results[1].status == "skipped"   # conditional (run_tests=false)
        assert results[2].status == "success"   # also-always

        # Factory should only be called for steps 1 and 3 (not skipped step)
        assert len(factory_calls) == 2

        ok("C3.3 Pipeline condition skip", f"statuses={[r.status for r in results]}")
    except Exception as e:
        fail("C3.3 Pipeline condition skip", str(e))

    # Test C3.4: Pipeline condition — step runs when condition is true
    try:
        workspace = Path(tempfile.mkdtemp(prefix="pipe_cond_true_"))

        steps = [
            PipelineStep(name="setup", prompt="Setup"),
            PipelineStep(name="test", prompt="Run tests", condition="{{run_tests}}"),
        ]
        config = PipelineConfig(
            name="test-condition-true",
            steps=steps,
            variables={"run_tests": "true"},
        )

        def factory(**kwargs):
            return MockAgent(MockAgentState(final_output="Done", status="success", cost=0.01))

        runner = PipelineRunner(config, factory, workspace_root=str(workspace))
        results = runner.run()

        assert len(results) == 2
        assert results[0].status == "success"
        assert results[1].status == "success"  # condition met

        ok("C3.4 Pipeline condition run", f"both steps ran")
    except Exception as e:
        fail("C3.4 Pipeline condition run", str(e))

    # Test C3.5: Pipeline output_var — variable passing between steps
    try:
        workspace = Path(tempfile.mkdtemp(prefix="pipe_outvar_"))

        steps = [
            PipelineStep(name="analyze", prompt="Analyze", output_var="analysis_result"),
            PipelineStep(name="implement", prompt="Implement based on: {{analysis_result}}"),
        ]
        config = PipelineConfig(name="test-output-var", steps=steps)

        call_count = 0

        def factory(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MockAgent(MockAgentState(
                    final_output="Found 3 issues: auth, logging, caching",
                    status="success",
                    cost=0.01,
                ))
            else:
                return MockAgent(MockAgentState(
                    final_output="Fixed all issues",
                    status="success",
                    cost=0.02,
                ))

        runner = PipelineRunner(config, factory, workspace_root=str(workspace))
        results = runner.run()

        assert len(results) == 2
        assert results[0].status == "success"
        assert results[1].status == "success"

        # Verify variable was captured and passed
        assert "analysis_result" in runner.variables
        assert "Found 3 issues" in runner.variables["analysis_result"]

        ok("C3.5 Pipeline output_var", f"var={runner.variables['analysis_result'][:50]}...")
    except Exception as e:
        fail("C3.5 Pipeline output_var", str(e))

    # Test C3.6: Pipeline checkpoint — git commit created
    try:
        workspace = Path(tempfile.mkdtemp(prefix="pipe_ckpt_"))

        steps = [
            PipelineStep(name="step-with-checkpoint", prompt="Do something", checkpoint=True),
        ]
        config = PipelineConfig(name="test-checkpoint", steps=steps)

        def factory(**kwargs):
            return MockAgent(MockAgentState(final_output="Done", status="success", cost=0.01))

        with patch("architect.features.pipelines.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(stdout="", returncode=0)
            runner = PipelineRunner(config, factory, workspace_root=str(workspace))
            results = runner.run()

        assert len(results) == 1
        assert results[0].status == "success"

        # Verify git commands were called for checkpoint
        git_calls = [
            c for c in mock_sp.call_args_list
            if c[0] and isinstance(c[0][0], list) and "git" in c[0][0]
        ]
        git_add_calls = [c for c in git_calls if "add" in c[0][0]]
        git_commit_calls = [c for c in git_calls if "commit" in c[0][0]]

        assert len(git_add_calls) >= 1, "Expected git add call for checkpoint"
        assert len(git_commit_calls) >= 1, "Expected git commit call for checkpoint"

        # Verify commit message contains checkpoint marker
        commit_call = git_commit_calls[0]
        commit_args = commit_call[0][0]
        assert "architect:checkpoint:step-with-checkpoint" in " ".join(commit_args)

        ok("C3.6 Pipeline checkpoint", f"git_adds={len(git_add_calls)}, git_commits={len(git_commit_calls)}")
    except Exception as e:
        fail("C3.6 Pipeline checkpoint", str(e))

    # Test C3.7: Pipeline from YAML with variables
    try:
        workspace = Path(tempfile.mkdtemp(prefix="pipe_yaml_"))

        yaml_content = textwrap.dedent("""\
            name: "yaml-pipeline"
            variables:
              greeting: "Hola"
              target: "World"
            steps:
              - name: greet
                agent: build
                prompt: "Say {{greeting}} to {{target}}"
              - name: conditional
                prompt: "Only if ready"
                condition: "{{ready}}"
        """)

        yaml_file = workspace / "pipeline.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        prompts = []

        def factory(**kwargs):
            agent = MockAgent(MockAgentState(final_output="Done", status="success", cost=0.01))
            orig = agent.run

            def capturing(p):
                prompts.append(p)
                return orig(p)

            agent.run = capturing
            return agent

        # Override "ready" variable from CLI
        runner = PipelineRunner.from_yaml(
            str(yaml_file),
            {"ready": "true"},
            factory,
            workspace_root=str(workspace),
        )
        results = runner.run()

        assert len(results) == 2
        assert results[0].status == "success"
        assert results[1].status == "success"  # ready=true from CLI override

        # Verify variable resolution in prompt
        assert "Hola" in prompts[0] and "World" in prompts[0], f"Variables not resolved: {prompts[0]}"

        ok("C3.7 Pipeline from YAML", f"steps={len(results)}, prompt_has_vars=True")
    except Exception as e:
        fail("C3.7 Pipeline from YAML", str(e))

    # Test C3.8: Pipeline dry-run
    try:
        workspace = Path(tempfile.mkdtemp(prefix="pipe_dry_"))

        steps = [
            PipelineStep(name="step1", prompt="Do X"),
            PipelineStep(name="step2", prompt="Do Y"),
        ]
        config = PipelineConfig(name="dry-run-test", steps=steps)

        factory_calls = []

        def factory(**kwargs):
            factory_calls.append(kwargs)
            return MockAgent(MockAgentState(final_output="Done", status="success"))

        runner = PipelineRunner(config, factory, workspace_root=str(workspace))
        results = runner.run(dry_run=True)

        assert len(results) == 2
        assert all(r.status == "dry_run" for r in results)
        assert len(factory_calls) == 0, "Factory should not be called in dry-run"

        ok("C3.8 Pipeline dry-run", f"steps={len(results)}, factory_calls={len(factory_calls)}")
    except Exception as e:
        fail("C3.8 Pipeline dry-run", str(e))

    # Test C3.9: Pipeline from-step (resume from specific step)
    try:
        workspace = Path(tempfile.mkdtemp(prefix="pipe_from_"))

        steps = [
            PipelineStep(name="step1", prompt="Already done"),
            PipelineStep(name="step2", prompt="Resume here"),
            PipelineStep(name="step3", prompt="And continue"),
        ]
        config = PipelineConfig(name="resume-test", steps=steps)

        factory_calls = []

        def factory(**kwargs):
            factory_calls.append(kwargs)
            return MockAgent(MockAgentState(final_output="Done", status="success", cost=0.01))

        runner = PipelineRunner(config, factory, workspace_root=str(workspace))
        results = runner.run(from_step="step2")

        assert len(results) == 2, f"Expected 2 results, got {len(results)}"
        assert results[0].step_name == "step2"
        assert results[1].step_name == "step3"

        ok("C3.9 Pipeline from-step", f"resumed from step2, ran {len(results)} steps")
    except Exception as e:
        fail("C3.9 Pipeline from-step", str(e))


# ══════════════════════════════════════════════════════════════════════════
# C4: CHECKPOINTS
# ══════════════════════════════════════════════════════════════════════════

def test_checkpoints_e2e():
    """Tests E2E del sistema de checkpoints."""
    section("C4. CHECKPOINTS — History y rollback")

    from architect.features.checkpoints import CheckpointManager, Checkpoint

    # Test C4.1: CheckpointManager list_checkpoints
    try:
        workspace = Path(tempfile.mkdtemp(prefix="ckpt_"))
        mgr = CheckpointManager(str(workspace))

        # Mock git log — format is %H|%s|%at (hash|subject|timestamp)
        with patch("architect.features.checkpoints.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(
                stdout="abc1234abc1234abc1234abc1234abc1234abcd|architect:checkpoint:step-1|1709000000\ndef5678def5678def5678def5678def5678defg|architect:checkpoint:step-2|1709001000\n",
                returncode=0,
            )
            checkpoints = mgr.list_checkpoints()

        assert len(checkpoints) == 2, f"Expected 2 checkpoints, got {len(checkpoints)}"
        assert checkpoints[0].step == 1
        assert checkpoints[1].step == 2
        assert checkpoints[0].commit_hash.startswith("abc1234")

        ok("C4.1 Checkpoint list", f"checkpoints={len(checkpoints)}")
    except Exception as e:
        fail("C4.1 Checkpoint list", str(e))

    # Test C4.2: CheckpointManager rollback
    try:
        workspace = Path(tempfile.mkdtemp(prefix="ckpt_rb_"))
        mgr = CheckpointManager(str(workspace))

        with patch("architect.features.checkpoints.subprocess.run") as mock_sp:
            def side_effect(*args, **kwargs):
                cmd = args[0] if args else kwargs.get("args", [])
                if isinstance(cmd, list) and "log" in cmd:
                    # format is %H|%s|%at
                    return MagicMock(
                        stdout="abc1234abc1234abc1234abc1234abc1234abcd|architect:checkpoint:step-1|1709000000\n",
                        returncode=0,
                    )
                return MagicMock(stdout="", returncode=0)

            mock_sp.side_effect = side_effect
            result = mgr.rollback(step=1)

        assert result is True

        ok("C4.2 Checkpoint rollback", "Rollback executed")
    except Exception as e:
        fail("C4.2 Checkpoint rollback", str(e))


# ══════════════════════════════════════════════════════════════════════════
# C5: AUTO-REVIEW
# ══════════════════════════════════════════════════════════════════════════

def test_auto_review_e2e():
    """Tests E2E del Auto-Review."""
    section("C5. AUTO-REVIEW — Review con contexto limpio")

    from architect.agents.reviewer import AutoReviewer, ReviewResult, REVIEW_SYSTEM_PROMPT

    # Test C5.1: Review with issues found
    try:
        def factory(**kwargs):
            return MockAgent(MockAgentState(
                final_output="- **[auth.py:15]** SQL injection en query. Usar parametrized queries.\n- **[config.py:8]** Secret hardcoded.",
                status="success",
                cost=0.03,
            ))

        reviewer = AutoReviewer(agent_factory=factory, review_model="gpt-4o")
        result = reviewer.review_changes(
            task="Implement user authentication",
            git_diff="diff --git a/auth.py\n+query = f'SELECT * FROM users WHERE id={user_id}'\n+SECRET = 'my-secret-key'",
        )

        assert isinstance(result, ReviewResult)
        assert result.has_issues is True
        assert "SQL injection" in result.review_text or "auth.py" in result.review_text
        assert result.cost == 0.03

        ok("C5.1 Review with issues", f"has_issues={result.has_issues}, cost=${result.cost:.4f}")
    except Exception as e:
        fail("C5.1 Review with issues", str(e))

    # Test C5.2: Review without issues
    try:
        def factory(**kwargs):
            return MockAgent(MockAgentState(
                final_output="Sin issues encontrados.",
                status="success",
                cost=0.02,
            ))

        reviewer = AutoReviewer(agent_factory=factory)
        result = reviewer.review_changes(
            task="Add logging",
            git_diff="diff --git a/app.py\n+import logging\n+logger = logging.getLogger(__name__)",
        )

        assert result.has_issues is False
        assert "sin issues" in result.review_text.lower()

        ok("C5.2 Review no issues", f"has_issues={result.has_issues}")
    except Exception as e:
        fail("C5.2 Review no issues", str(e))

    # Test C5.3: Review with empty diff
    try:
        reviewer = AutoReviewer(agent_factory=MagicMock())
        result = reviewer.review_changes(task="Nothing", git_diff="")

        assert result.has_issues is False
        assert "sin cambios" in result.review_text.lower()

        ok("C5.3 Review empty diff", f"text={result.review_text[:50]}")
    except Exception as e:
        fail("C5.3 Review empty diff", str(e))

    # Test C5.4: Review passes correct model to factory
    try:
        factory_calls = []

        def factory_capture(**kwargs):
            factory_calls.append(kwargs)
            return MockAgent(MockAgentState(final_output="Sin issues encontrados.", cost=0.01))

        reviewer = AutoReviewer(agent_factory=factory_capture, review_model="claude-sonnet-4-6")
        reviewer.review_changes(task="Test", git_diff="diff --git a/f.py\n+pass")

        assert len(factory_calls) == 1
        assert factory_calls[0].get("agent") == "review"
        assert factory_calls[0].get("model") == "claude-sonnet-4-6"

        ok("C5.4 Review model pass-through", f"agent={factory_calls[0]['agent']}, model={factory_calls[0]['model']}")
    except Exception as e:
        fail("C5.4 Review model pass-through", str(e))

    # Test C5.5: Review builds fix prompt
    try:
        fix_prompt = AutoReviewer.build_fix_prompt(
            "- **[auth.py:15]** SQL injection. Use parameterized queries."
        )

        assert "reviewer" in fix_prompt.lower() or "problemas" in fix_prompt.lower()
        assert "SQL injection" in fix_prompt
        assert "auth.py" in fix_prompt

        ok("C5.5 Build fix prompt", f"prompt_len={len(fix_prompt)}")
    except Exception as e:
        fail("C5.5 Build fix prompt", str(e))

    # Test C5.6: get_recent_diff
    try:
        workspace = Path(tempfile.mkdtemp(prefix="review_diff_"))

        with patch("architect.agents.reviewer.subprocess.run") as mock_sp:
            mock_sp.return_value = MagicMock(
                stdout="diff --git a/file.py\n+new line\n",
                returncode=0,
            )
            diff = AutoReviewer.get_recent_diff(str(workspace), commits_back=2)

        assert "diff --git" in diff

        ok("C5.6 get_recent_diff", f"diff_len={len(diff)}")
    except Exception as e:
        fail("C5.6 get_recent_diff", str(e))

    # Test C5.7: Review with agent error
    try:
        def factory_error(**kwargs):
            agent = MagicMock()
            agent.run.side_effect = RuntimeError("LLM API timeout")
            return agent

        reviewer = AutoReviewer(agent_factory=factory_error)
        result = reviewer.review_changes(task="Test", git_diff="diff +x")

        assert result.has_issues is False  # Error → no issues (safe default)
        assert "error" in result.review_text.lower()

        ok("C5.7 Review error handling", f"graceful error handling")
    except Exception as e:
        fail("C5.7 Review error handling", str(e))

    # Test C5.8: REVIEW_SYSTEM_PROMPT content
    try:
        assert "reviewer" in REVIEW_SYSTEM_PROMPT.lower() or "review" in REVIEW_SYSTEM_PROMPT.lower()
        assert "bug" in REVIEW_SYSTEM_PROMPT.lower() or "seguridad" in REVIEW_SYSTEM_PROMPT.lower()
        assert len(REVIEW_SYSTEM_PROMPT) > 100

        ok("C5.8 System prompt", f"len={len(REVIEW_SYSTEM_PROMPT)}")
    except Exception as e:
        fail("C5.8 System prompt", str(e))


# ══════════════════════════════════════════════════════════════════════════
# GUARDRAILS E2E (BUG-2 verification)
# ══════════════════════════════════════════════════════════════════════════

def test_guardrails_e2e():
    """Tests E2E de guardrails — verifica que protected_files funciona."""
    section("GUARDRAILS E2E — protected_files + apply_patch")

    from architect.config.schema import GuardrailsConfig
    from architect.core.guardrails import GuardrailsEngine
    from architect.execution.engine import ExecutionEngine
    from architect.config.schema import AppConfig

    # Test G1: check_file_access blocks .env
    try:
        config = GuardrailsConfig(
            enabled=True,
            protected_files=[".env", ".env.*", "*.pem", "*.key", "secrets.yaml"],
        )
        engine = GuardrailsEngine(config=config, workspace_root="/tmp")

        # Direct .env
        allowed, reason = engine.check_file_access(".env", "write_file")
        assert not allowed, "Should block .env"

        # .env.production
        allowed, _ = engine.check_file_access(".env.production", "write_file")
        assert not allowed, "Should block .env.production"

        # Nested path
        allowed, _ = engine.check_file_access("config/.env", "write_file")
        assert not allowed, "Should block config/.env (basename match)"

        # Non-protected
        allowed, _ = engine.check_file_access("app.py", "write_file")
        assert allowed, "Should allow app.py"

        ok("G1 check_file_access", "All patterns correctly blocked/allowed")
    except Exception as e:
        fail("G1 check_file_access", str(e))

    # Test G2: ExecutionEngine.check_guardrails includes apply_patch
    try:
        config = GuardrailsConfig(
            enabled=True,
            protected_files=[".env"],
        )
        guardrails = GuardrailsEngine(config=config, workspace_root="/tmp")

        # Create a minimal ExecutionEngine with guardrails
        from architect.tools.registry import ToolRegistry

        registry = ToolRegistry()
        # We need a minimal AppConfig
        from architect.config.loader import load_config
        app_config = load_config()  # default config

        engine = ExecutionEngine(registry, app_config, guardrails=guardrails)

        # Test apply_patch is now checked
        result = engine.check_guardrails("apply_patch", {"path": ".env"})
        assert result is not None, "apply_patch to .env should be blocked"
        assert "protegido" in result.output.lower() or "guardrail" in result.output.lower()

        # Test write_file still checked
        result = engine.check_guardrails("write_file", {"path": ".env"})
        assert result is not None, "write_file to .env should be blocked"

        # Test read_file NOT checked (read-only)
        result = engine.check_guardrails("read_file", {"path": ".env"})
        assert result is None, "read_file should not be blocked"

        ok("G2 ExecutionEngine.check_guardrails", "apply_patch + write_file blocked, read_file allowed")
    except Exception as e:
        fail("G2 ExecutionEngine.check_guardrails", str(e))

    # Test G3: Blocked commands
    try:
        config = GuardrailsConfig(
            enabled=True,
            blocked_commands=[r"rm\s+-[rf]+\s+/", r"DROP\s+TABLE"],
        )
        engine = GuardrailsEngine(config=config, workspace_root="/tmp")

        allowed, _ = engine.check_command("rm -rf /")
        assert not allowed, "Should block rm -rf /"

        allowed, _ = engine.check_command("DROP TABLE users")
        assert not allowed, "Should block DROP TABLE"

        allowed, _ = engine.check_command("ls -la")
        assert allowed, "Should allow ls"

        ok("G3 Blocked commands", "Dangerous commands blocked, safe allowed")
    except Exception as e:
        fail("G3 Blocked commands", str(e))

    # Test G4: Redirect to protected file blocked
    try:
        config = GuardrailsConfig(
            enabled=True,
            protected_files=[".env", "*.key"],
        )
        engine = GuardrailsEngine(config=config, workspace_root="/tmp")

        allowed, _ = engine.check_command("echo SECRET=xyz > .env")
        assert not allowed, "Should block redirect to .env"

        allowed, _ = engine.check_command("cat data | tee server.key")
        assert not allowed, "Should block tee to .key"

        allowed, _ = engine.check_command("echo hello > output.txt")
        assert allowed, "Should allow redirect to non-protected file"

        ok("G4 Redirect to protected file", "Shell redirections to protected files blocked")
    except Exception as e:
        fail("G4 Redirect to protected file", str(e))


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "═" * 60)
    print("  ARCHITECT CLI — Phase C E2E Tests")
    print("═" * 60)

    test_ralph_loop_e2e()
    test_parallel_e2e()
    test_pipeline_e2e()
    test_checkpoints_e2e()
    test_auto_review_e2e()
    test_guardrails_e2e()

    print("\n" + "═" * 60)
    print(f"  RESULTADO: {_passed} passed, {_failed} failed")
    print("═" * 60)

    if _errors:
        print("\n  Errores:")
        for err in _errors:
            print(f"    ✗ {err}")

    print()
    sys.exit(0 if _failed == 0 else 1)


if __name__ == "__main__":
    main()
