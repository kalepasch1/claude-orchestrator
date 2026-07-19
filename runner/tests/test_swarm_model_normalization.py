import parallel_dispatch


REGISTRY = {
    "openai": {"models": {"fast": "gpt-fast", "mid": "gpt-mid", "heavy": "gpt-heavy"}},
    "gemini": {"models": {"fast": "gemini-fast", "mid": "gemini-mid", "heavy": "gemini-heavy"}},
}


def test_generic_openai_route_resolves_to_real_mid_tier_model():
    provider, model = parallel_dispatch._normalized_swarm_model(
        "openai", "openai", {"kind": "build"}, REGISTRY)

    assert provider == "openai"
    assert model == "gpt-mid"


def test_google_alias_and_material_risk_select_gemini_heavy():
    provider, model = parallel_dispatch._normalized_swarm_model(
        "google", "google", {"kind": "build", "material": True}, REGISTRY)

    assert provider == "gemini"
    assert model == "gemini-heavy"


def test_provider_specific_model_is_preserved():
    provider, model = parallel_dispatch._normalized_swarm_model(
        "openai", "gpt-future", {"kind": "build"}, REGISTRY)

    assert provider == "openai"
    assert model == "gpt-future"
