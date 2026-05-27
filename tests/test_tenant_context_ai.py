"""sky-poc-ai tenant context + Bedrock profile lookup (Projeto A — PR #9/#10)."""

from __future__ import annotations

import os
import uuid

import pytest

from core.tenant_context import (
    DEFAULT_TENANT_CONTEXT,
    TenantContext,
    current_tenant,
    multi_tenant_enabled,
    reset_current_tenant,
    set_current_tenant,
)


# ── Defaults ────────────────────────────────────────────────────────


def test_default_context_identity():
    assert current_tenant() is DEFAULT_TENANT_CONTEXT
    assert DEFAULT_TENANT_CONTEXT.is_default is True
    assert DEFAULT_TENANT_CONTEXT.bedrock_inference_profile_arn is None


def test_multi_tenant_enabled_defaults_off(monkeypatch):
    monkeypatch.delenv("MULTI_TENANT_ENABLED", raising=False)
    assert multi_tenant_enabled() is False


@pytest.mark.parametrize("v", ["true", "1", "yes", "on", "TRUE", "YES"])
def test_multi_tenant_enabled_truthy_values(monkeypatch, v):
    monkeypatch.setenv("MULTI_TENANT_ENABLED", v)
    assert multi_tenant_enabled() is True


@pytest.mark.parametrize("v", ["false", "0", "no", "off", "", "anything-else"])
def test_multi_tenant_enabled_falsy_values(monkeypatch, v):
    monkeypatch.setenv("MULTI_TENANT_ENABLED", v)
    assert multi_tenant_enabled() is False


# ── Contextvar plumbing ────────────────────────────────────────────


def test_set_and_reset_current_tenant():
    ctx = TenantContext(
        slug="gbt",
        id=uuid.uuid4(),
        tier="pilot",
        display_name="GBT",
        bedrock_inference_profile_arn=(
            "arn:aws:bedrock:eu-west-1:0:application-inference-profile/sky-gbt"
        ),
    )
    token = set_current_tenant(ctx)
    try:
        assert current_tenant() is ctx
    finally:
        reset_current_tenant(token)
    assert current_tenant() is DEFAULT_TENANT_CONTEXT


# ── Bedrock provider with tenant inference profile ────────────────


def test_bedrock_provider_uses_inference_profile_arn_when_supplied():
    """The provider must report the ARN as its model_name when set."""
    pytest.importorskip("langchain_aws")

    # Stub out ChatBedrockConverse so the test doesn't touch AWS.
    import core.llm.providers as providers_mod

    class _FakeConverse:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatched = False
    try:
        import langchain_aws  # type: ignore

        original = langchain_aws.ChatBedrockConverse
        langchain_aws.ChatBedrockConverse = _FakeConverse
        monkeypatched = True
    except ImportError:
        pytest.skip("langchain_aws not installed")

    try:
        arn = (
            "arn:aws:bedrock:eu-west-1:0:application-inference-profile/sky-gbt"
        )
        provider = providers_mod.BedrockChatProvider(
            model="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
            inference_profile_arn=arn,
        )
        assert provider.model_name == arn
        assert (
            provider.base_model_id
            == "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
        )
        # The underlying ChatBedrockConverse received the ARN as model.
        assert provider._chat.kwargs["model"] == arn  # type: ignore[attr-defined]
    finally:
        if monkeypatched:
            langchain_aws.ChatBedrockConverse = original  # type: ignore


def test_bedrock_provider_falls_back_to_model_id_without_arn():
    pytest.importorskip("langchain_aws")

    import core.llm.providers as providers_mod

    class _FakeConverse:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    import langchain_aws  # type: ignore

    original = langchain_aws.ChatBedrockConverse
    langchain_aws.ChatBedrockConverse = _FakeConverse
    try:
        model_id = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
        provider = providers_mod.BedrockChatProvider(model=model_id)
        assert provider.model_name == model_id
        assert provider.inference_profile_arn is None
    finally:
        langchain_aws.ChatBedrockConverse = original  # type: ignore


# ── factory._tenant_bedrock_profile_arn helper ─────────────────────


def test_tenant_bedrock_profile_arn_returns_none_for_default():
    from core.llm.factory import _tenant_bedrock_profile_arn

    # Make sure no leftover context from another test interferes.
    set_current_tenant(DEFAULT_TENANT_CONTEXT)
    assert _tenant_bedrock_profile_arn() is None


def test_tenant_bedrock_profile_arn_returns_arn_when_set():
    from core.llm.factory import _tenant_bedrock_profile_arn

    arn = "arn:aws:bedrock:eu-west-1:0:application-inference-profile/sky-gbt"
    ctx = TenantContext(
        slug="gbt",
        id=uuid.uuid4(),
        tier="pilot",
        display_name="GBT",
        bedrock_inference_profile_arn=arn,
    )
    token = set_current_tenant(ctx)
    try:
        assert _tenant_bedrock_profile_arn() == arn
    finally:
        reset_current_tenant(token)


def test_tenant_bedrock_profile_arn_returns_none_when_tenant_has_no_arn():
    from core.llm.factory import _tenant_bedrock_profile_arn

    ctx = TenantContext(
        slug="gbt",
        id=uuid.uuid4(),
        tier="pilot",
        display_name="GBT",
        bedrock_inference_profile_arn=None,  # not set yet
    )
    token = set_current_tenant(ctx)
    try:
        assert _tenant_bedrock_profile_arn() is None
    finally:
        reset_current_tenant(token)


# ── Tenant registry lookup ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_lookup_tenant_returns_none_for_unknown_slug():
    from core.tenant_registry_lookup import (
        clear_cache,
        lookup_tenant_by_slug,
    )

    clear_cache()

    class _Session:
        async def execute(self, *_args, **_kwargs):
            # Simulate the "no row" result shape.
            class _Result:
                def mappings(self):
                    class _M:
                        def one_or_none(self):
                            return None

                    return _M()

            return _Result()

    ctx = await lookup_tenant_by_slug(_Session(), "ghost")
    assert ctx is None


@pytest.mark.asyncio
async def test_lookup_tenant_returns_context_for_known_slug():
    from core.tenant_registry_lookup import (
        clear_cache,
        lookup_tenant_by_slug,
    )

    clear_cache()

    fake_row = {
        "id": uuid.uuid4(),
        "slug": "gbt",
        "tier": "pilot",
        "display_name": "GBT S.A.",
        "bedrock_inference_profile_arn": (
            "arn:aws:bedrock:eu-west-1:0:application-inference-profile/sky-gbt"
        ),
        "rate_limit_rpm": 60,
        "rate_limit_tpm": 50000,
        "is_active": True,
        "feature_flags": {},
    }

    class _Session:
        async def execute(self, *_args, **_kwargs):
            class _Result:
                def mappings(self):
                    class _M:
                        def one_or_none(self_inner):
                            return fake_row

                    return _M()

            return _Result()

    ctx = await lookup_tenant_by_slug(_Session(), "gbt")
    assert ctx is not None
    assert ctx.slug == "gbt"
    assert ctx.tier == "pilot"
    assert ctx.bedrock_inference_profile_arn == fake_row[
        "bedrock_inference_profile_arn"
    ]
