"""Tests for two-phase sandbox (QW8)."""

from __future__ import annotations

import pytest

from attocode.integrations.safety.sandbox import (
    SandboxPhase,
    TwoPhaseContext,
    create_sandbox,
    create_two_phase_sandbox,
)
from attocode.integrations.safety.sandbox.basic import BasicSandbox


class TestSandboxPhaseEnum:
    def test_values(self) -> None:
        assert SandboxPhase.SETUP == "setup"
        assert SandboxPhase.AGENT == "agent"

    def test_members(self) -> None:
        assert set(SandboxPhase) == {SandboxPhase.SETUP, SandboxPhase.AGENT}


class TestTwoPhaseContextLifecycle:
    def test_starts_in_setup_phase(self) -> None:
        ctx = TwoPhaseContext(sandbox_mode="basic")
        assert ctx.phase == SandboxPhase.SETUP

    def test_transition_to_agent(self) -> None:
        ctx = TwoPhaseContext(sandbox_mode="basic")
        ctx.transition_to_agent()
        assert ctx.phase == SandboxPhase.AGENT

    def test_double_transition_raises(self) -> None:
        ctx = TwoPhaseContext(sandbox_mode="basic")
        ctx.transition_to_agent()
        with pytest.raises(RuntimeError, match="Already in agent phase"):
            ctx.transition_to_agent()


class TestTwoPhaseContextSandboxes:
    def test_setup_sandbox_has_network(self) -> None:
        ctx = TwoPhaseContext(sandbox_mode="basic")
        sb = ctx.get_sandbox()
        assert isinstance(sb, BasicSandbox)
        assert sb.options.network_allowed is True

    def test_agent_sandbox_no_network(self) -> None:
        ctx = TwoPhaseContext(sandbox_mode="basic")
        ctx.transition_to_agent()
        sb = ctx.get_sandbox()
        assert isinstance(sb, BasicSandbox)
        assert sb.options.network_allowed is False

    def test_sandboxes_are_cached(self) -> None:
        ctx = TwoPhaseContext(sandbox_mode="basic")
        sb1 = ctx.get_sandbox()
        sb2 = ctx.get_sandbox()
        assert sb1 is sb2

        ctx.transition_to_agent()
        sb3 = ctx.get_sandbox()
        sb4 = ctx.get_sandbox()
        assert sb3 is sb4
        assert sb1 is not sb3

    def test_setup_and_agent_are_different_instances(self) -> None:
        ctx = TwoPhaseContext(sandbox_mode="basic")
        setup_sb = ctx.get_sandbox()
        ctx.transition_to_agent()
        agent_sb = ctx.get_sandbox()
        assert setup_sb is not agent_sb


class TestCreateTwoPhaseSandbox:
    def test_returns_context(self) -> None:
        ctx = create_two_phase_sandbox(mode="basic")
        assert isinstance(ctx, TwoPhaseContext)

    def test_starts_in_setup(self) -> None:
        ctx = create_two_phase_sandbox(mode="basic")
        assert ctx.phase == SandboxPhase.SETUP

    def test_full_lifecycle(self) -> None:
        ctx = create_two_phase_sandbox(mode="basic")

        # Setup phase: network on
        setup_sb = ctx.get_sandbox()
        assert setup_sb.options.network_allowed is True

        # Transition
        ctx.transition_to_agent()

        # Agent phase: network off
        agent_sb = ctx.get_sandbox()
        assert agent_sb.options.network_allowed is False


class TestCreateSandboxNetworkOverride:
    def test_network_allowed_true(self) -> None:
        sb = create_sandbox("basic", network_allowed=True)
        assert isinstance(sb, BasicSandbox)
        assert sb.options.network_allowed is True

    def test_network_allowed_false(self) -> None:
        sb = create_sandbox("basic", network_allowed=False)
        assert isinstance(sb, BasicSandbox)
        assert sb.options.network_allowed is False

    def test_network_allowed_none_uses_default(self) -> None:
        sb = create_sandbox("basic")
        assert isinstance(sb, BasicSandbox)
        # BasicSandbox default is True
        assert sb.options.network_allowed is True


class TestTwoPhaseExecution:
    @pytest.mark.asyncio
    async def test_setup_phase_execute(self) -> None:
        ctx = create_two_phase_sandbox(mode="basic")
        sb = ctx.get_sandbox()
        output, code = await sb.execute("echo setup")
        assert code == 0
        assert "setup" in output

    @pytest.mark.asyncio
    async def test_agent_phase_execute(self) -> None:
        ctx = create_two_phase_sandbox(mode="basic")
        ctx.transition_to_agent()
        sb = ctx.get_sandbox()
        output, code = await sb.execute("echo agent")
        assert code == 0
        assert "agent" in output
