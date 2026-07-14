import model_catalog
import model_gateway
import model_policy
import provider_credentials


def test_grok_alias_enables_xai_without_copying_secret_to_disk(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("GROK_API_KEY", "test-grok-credential")

    assert provider_credentials.has("xai")
    assert "xai" in model_gateway.configured()


def test_xai_and_groq_models_participate_in_concrete_catalog(monkeypatch):
    import provider_failover_sla
    monkeypatch.setattr(provider_failover_sla, "is_demoted", lambda provider: False)
    xai = model_catalog.ranked("plan", need=8, available_providers={"xai"}, use_empirical=False)
    groq = model_catalog.ranked("review", need=7, available_providers={"groq"}, use_empirical=False)

    assert {c["provider"] for c in xai} == {"xai"}
    assert any(c["model"].startswith("grok-") for c in xai)
    assert {c["provider"] for c in groq} == {"groq"}


def test_diverse_qa_route_rotates_vendor_families(monkeypatch):
    ranked = [
        {"provider": "local", "model": "deepseek-coder-v2:16b", "vendor_family": "deepseek-local", "optimizer_score": 3},
        {"provider": "xai", "model": "grok-4.3", "vendor_family": "xai", "optimizer_score": 2},
        {"provider": "openai", "model": "gpt-5.5", "vendor_family": "openai", "optimizer_score": 1},
    ]
    monkeypatch.setattr(model_catalog, "ranked", lambda *a, **k: ranked)
    monkeypatch.setattr(model_policy.mg, "available", lambda: ["local", "xai", "openai"])
    model_policy._DIVERSE_INDEX = 0

    picks = [model_policy.choose_diverse("review", need=7)[0] for _ in range(3)]

    assert picks == ["local", "xai", "openai"]


def test_local_deepseek_and_mistral_are_independent_qa_families():
    assert model_catalog.vendor_family("local", "deepseek-coder-v2:16b") == "deepseek-local"
    assert model_catalog.vendor_family("local", "codestral:22b") == "mistral-local"


def test_auth_demoted_provider_is_removed_from_optimizer(monkeypatch):
    import provider_failover_sla
    monkeypatch.setattr(provider_failover_sla, "is_demoted", lambda provider: provider == "xai")

    ranked = model_catalog.ranked("plan", need=8, available_providers={"xai"}, use_empirical=False)

    assert ranked == []


def test_auth_demotion_survives_control_plane_write_failure(monkeypatch, tmp_path):
    import provider_failover_sla
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setattr(provider_failover_sla.db, "upsert", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(provider_failover_sla.db, "select", lambda *a, **k: [])

    provider_failover_sla.demote("xai", "auth-403")

    assert provider_failover_sla.is_demoted("xai")
    assert (tmp_path / "provider_sla_state.json").exists()


def test_replacing_auth_credential_releases_old_quarantine(monkeypatch, tmp_path):
    import provider_failover_sla
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setenv("XAI_API_KEY", "old-key")
    monkeypatch.setattr(provider_failover_sla.db, "upsert", lambda *a, **k: None)
    monkeypatch.setattr(provider_failover_sla.db, "select", lambda *a, **k: [])
    provider_failover_sla.demote("xai", "auth-403")
    assert provider_failover_sla.is_demoted("xai")

    monkeypatch.setenv("XAI_API_KEY", "replacement-key")

    assert not provider_failover_sla.is_demoted("xai")


def test_successful_same_key_probe_releases_credit_quarantine(monkeypatch, tmp_path):
    import provider_failover_sla
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setenv("XAI_API_KEY", "same-key")
    monkeypatch.setattr(provider_failover_sla.db, "upsert", lambda *a, **k: None)
    monkeypatch.setattr(provider_failover_sla.db, "select", lambda *a, **k: [])
    provider_failover_sla.demote("xai", "auth-403")

    assert provider_failover_sla.record_probe_success("xai") is True
    assert not provider_failover_sla.is_demoted("xai")


def test_provider_state_cache_avoids_repeated_control_plane_reads(monkeypatch, tmp_path):
    import provider_failover_sla
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    monkeypatch.setenv("ORCH_PROVIDER_SLA_CACHE_SEC", "30")
    provider_failover_sla._LOAD_CACHE.update({"at": 0.0, "path": "", "state": None})
    calls = []
    monkeypatch.setattr(provider_failover_sla.db, "select", lambda *a, **k: calls.append(1) or [])
    provider_failover_sla._load(); provider_failover_sla._load()
    assert len(calls) == 1
