#!/usr/bin/env python3.12
"""
Test manual F14: Cost Tracking + Prompt Caching + Local LLM Cache.

Verifica que todos los componentes funcionan correctamente sin necesitar
una API key ni conexión al LLM.

Ejecutar desde la raíz del proyecto:
    python3.12 scripts/test_phase14.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_model_pricing():
    from architect.costs.prices import ModelPricing, PriceLoader

    # Precios exactos
    loader = PriceLoader()
    pricing = loader.get_prices("gpt-4o")
    assert pricing.input_per_million == 2.5, f"Expected 2.5, got {pricing.input_per_million}"
    assert pricing.output_per_million == 10.0
    assert pricing.cached_input_per_million == 1.25
    print("  ✓ PriceLoader exact match OK")

    # Prefix match (modelo con variante)
    pricing2 = loader.get_prices("claude-sonnet-4-6-20250514")
    assert pricing2.input_per_million == 3.0, f"Expected 3.0, got {pricing2.input_per_million}"
    print("  ✓ PriceLoader prefix match OK")

    # Fallback para modelo desconocido
    pricing3 = loader.get_prices("unknown-model-xyz")
    assert pricing3.input_per_million == 3.0  # fallback
    assert pricing3.output_per_million == 15.0
    print("  ✓ PriceLoader fallback OK")

    # Ollama (coste 0)
    pricing4 = loader.get_prices("ollama/llama3")
    assert pricing4.input_per_million == 0.0
    assert pricing4.output_per_million == 0.0
    print("  ✓ PriceLoader ollama (coste 0) OK")

    return True


def test_cost_tracker():
    from architect.costs.tracker import BudgetExceededError, CostTracker
    from architect.costs.prices import PriceLoader

    loader = PriceLoader()
    tracker = CostTracker(price_loader=loader)

    # Registrar un step
    usage = {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200}
    tracker.record(step=0, model="gpt-4o", usage=usage, source="agent")

    assert tracker.total_input_tokens == 1000
    assert tracker.total_output_tokens == 200
    assert tracker.total_cached_tokens == 0
    assert tracker.has_data()
    print("  ✓ CostTracker.record básico OK")

    # Coste calculado: 1000/1M * $2.5 + 200/1M * $10 = $0.0025 + $0.002 = $0.0045
    expected_cost = (1000 / 1_000_000) * 2.5 + (200 / 1_000_000) * 10.0
    assert abs(tracker.total_cost_usd - expected_cost) < 1e-7, \
        f"Expected {expected_cost}, got {tracker.total_cost_usd}"
    print("  ✓ CostTracker cálculo de coste OK")

    # Con cached tokens
    usage2 = {
        "prompt_tokens": 2000,
        "completion_tokens": 300,
        "cache_read_input_tokens": 1500,
    }
    tracker.record(step=1, model="gpt-4o", usage=usage2, source="agent")
    assert tracker.total_cached_tokens == 1500
    print("  ✓ CostTracker cached tokens OK")

    # Summary
    summary = tracker.summary()
    assert "total_input_tokens" in summary
    assert "total_cost_usd" in summary
    assert "by_source" in summary
    assert "agent" in summary["by_source"]
    print("  ✓ CostTracker.summary() OK")

    # format_summary_line
    line = tracker.format_summary_line()
    assert "$" in line
    assert "in" in line
    assert "out" in line
    assert "cached" in line
    print("  ✓ CostTracker.format_summary_line() OK")

    # Budget enforcement
    tracker_budget = CostTracker(
        price_loader=loader,
        budget_usd=0.000001,  # presupuesto casi 0
    )
    raised = False
    try:
        tracker_budget.record(step=0, model="gpt-4o",
                              usage={"prompt_tokens": 100, "completion_tokens": 50})
    except BudgetExceededError:
        raised = True
    assert raised, "BudgetExceededError no fue lanzado"
    print("  ✓ BudgetExceededError OK")

    # Warn threshold (sin excepción)
    warnings = []
    tracker_warn = CostTracker(
        price_loader=loader,
        warn_at_usd=0.000001,  # umbral bajo
    )
    tracker_warn.record(step=0, model="gpt-4o",
                        usage={"prompt_tokens": 100, "completion_tokens": 50})
    # El warning se emite a structlog — solo verificamos que no lanza
    print("  ✓ warn_at_usd (sin excepción) OK")

    return True


def test_local_llm_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        from architect.llm.cache import LocalLLMCache
        from architect.llm.adapter import LLMResponse, ToolCall

        cache = LocalLLMCache(cache_dir=Path(tmpdir), ttl_hours=1)

        messages = [{"role": "user", "content": "hola"}]
        tools = None

        # Miss inicial
        result = cache.get(messages, tools)
        assert result is None
        print("  ✓ LocalLLMCache miss OK")

        # Set
        response = LLMResponse(
            content="Hola, ¿cómo estás?",
            tool_calls=[],
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18,
                   "cache_read_input_tokens": 0},
        )
        cache.set(messages, tools, response)

        # Hit
        cached = cache.get(messages, tools)
        assert cached is not None
        assert cached.content == "Hola, ¿cómo estás?"
        assert cached.finish_reason == "stop"
        print("  ✓ LocalLLMCache set/get OK")

        # Diferentes mensajes → miss
        other_messages = [{"role": "user", "content": "adiós"}]
        result2 = cache.get(other_messages, tools)
        assert result2 is None
        print("  ✓ LocalLLMCache key diferente → miss OK")

        # Stats
        stats = cache.stats()
        assert stats["entries"] == 1
        assert stats["expired"] == 0
        print("  ✓ LocalLLMCache.stats() OK")

        # Clear
        cleared = cache.clear()
        assert cleared == 1
        stats2 = cache.stats()
        assert stats2["entries"] == 0
        print("  ✓ LocalLLMCache.clear() OK")

    return True


def test_config_schema():
    from architect.config.schema import AppConfig

    cfg = AppConfig()
    assert hasattr(cfg, "costs"), "AppConfig sin campo 'costs'"
    assert hasattr(cfg, "llm_cache"), "AppConfig sin campo 'llm_cache'"
    assert cfg.llm.prompt_caching is False, "prompt_caching debe ser False por defecto"
    assert cfg.costs.enabled is True
    assert cfg.costs.budget_usd is None
    assert cfg.llm_cache.enabled is False
    assert cfg.llm_cache.ttl_hours == 24
    print("  ✓ AppConfig.costs y llm_cache OK")
    print("  ✓ LLMConfig.prompt_caching OK")
    return True


def test_llm_adapter_caching_methods():
    """Verifica que _prepare_messages_with_caching funciona correctamente."""
    from architect.config.schema import LLMConfig
    from architect.llm.adapter import LLMAdapter

    # Sin caching
    cfg_no_cache = LLMConfig(model="gpt-4o-mini", prompt_caching=False)
    adapter = LLMAdapter(cfg_no_cache)
    messages = [{"role": "system", "content": "Eres un asistente."}, {"role": "user", "content": "Hola"}]
    result = adapter._prepare_messages_with_caching(messages)
    assert result == messages, "Sin caching, los mensajes no deben cambiar"
    print("  ✓ _prepare_messages_with_caching sin caching OK")

    # Con caching
    cfg_cache = LLMConfig(model="claude-sonnet-4-6", prompt_caching=True)
    adapter_cache = LLMAdapter(cfg_cache)
    result2 = adapter_cache._prepare_messages_with_caching(messages)
    system_msg = result2[0]
    assert isinstance(system_msg["content"], list), "Con caching, content debe ser lista"
    assert system_msg["content"][0]["type"] == "text"
    assert "cache_control" in system_msg["content"][0]
    assert system_msg["content"][0]["cache_control"] == {"type": "ephemeral"}
    # Mensaje user no debe cambiar
    assert result2[1] == messages[1]
    print("  ✓ _prepare_messages_with_caching con caching OK")

    return True


def test_agent_state_cost_tracker():
    from architect.core.state import AgentState
    from architect.costs.tracker import CostTracker
    from architect.costs.prices import PriceLoader

    state = AgentState()
    assert state.cost_tracker is None
    print("  ✓ AgentState.cost_tracker None por defecto OK")

    # Con cost_tracker
    loader = PriceLoader()
    tracker = CostTracker(price_loader=loader)
    tracker.record(step=0, model="gpt-4o",
                   usage={"prompt_tokens": 500, "completion_tokens": 100})

    state.cost_tracker = tracker
    output = state.to_output_dict()
    assert "costs" in output, "to_output_dict() debe incluir 'costs' cuando hay tracker"
    assert "total_cost_usd" in output["costs"]
    print("  ✓ AgentState.to_output_dict() incluye costs OK")

    return True


def main():
    print("=" * 60)
    print("Test F14: Cost Tracking + Prompt Caching + Local LLM Cache")
    print("=" * 60)

    tests = [
        ("ModelPricing y PriceLoader", test_model_pricing),
        ("CostTracker", test_cost_tracker),
        ("LocalLLMCache", test_local_llm_cache),
        ("AppConfig (costs, llm_cache, prompt_caching)", test_config_schema),
        ("LLMAdapter._prepare_messages_with_caching()", test_llm_adapter_caching_methods),
        ("AgentState.cost_tracker + to_output_dict()", test_agent_state_cost_tracker),
    ]

    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n▶ {name}")
        try:
            test_fn()
            passed += 1
        except Exception as e:
            import traceback
            print(f"  ✗ FALLÓ: {e}")
            traceback.print_exc()
            failed += 1

    print()
    print("=" * 60)
    if failed == 0:
        print(f"✅ Todos los checks pasaron ({passed}/{passed})")
        sys.exit(0)
    else:
        print(f"❌ {failed} checks fallaron ({passed}/{passed + failed} OK)")
        sys.exit(1)


if __name__ == "__main__":
    main()
