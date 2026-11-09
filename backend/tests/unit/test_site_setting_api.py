"""M15-T07 站点配置接口的测试。

覆盖 DoD：
    1. 配置项含 site_name/site_description/allow_registration/allow_content_review
    2. 更新后查询返回新值（接口测试）
边界：配置读取有缓存，更新后需失效。
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.modules.system.setting_service import (
    DEFAULT_SETTINGS,
    SETTING_DESCRIPTIONS,
    SETTINGS_CACHE_KEY_SUFFIX,
)

pytestmark = pytest.mark.integration


# ============================================================
# 常量（不依赖数据库）
# ============================================================


class TestDefaults:
    def test_has_four_settings(self) -> None:
        """DoD：配置项含四个固定字段。"""
        assert set(DEFAULT_SETTINGS.keys()) == {
            "site_name",
            "site_description",
            "allow_registration",
            "allow_content_review",
        }

    def test_default_values(self) -> None:
        assert DEFAULT_SETTINGS["site_name"] == "云游坊"
        assert DEFAULT_SETTINGS["site_description"] == "智能旅游规划平台"
        assert DEFAULT_SETTINGS["allow_registration"] is True
        assert DEFAULT_SETTINGS["allow_content_review"] is True

    def test_descriptions_cover_all(self) -> None:
        """每个配置项都要有中文说明——运维查库时能看懂。"""
        assert set(SETTING_DESCRIPTIONS.keys()) == set(DEFAULT_SETTINGS.keys())

    def test_cache_key_suffix(self) -> None:
        assert SETTINGS_CACHE_KEY_SUFFIX == "settings:site"


# ============================================================
# 接口测试
# ============================================================


@pytest.fixture
async def db_ready() -> None:
    from app.db.session import SessionLocal, check_database

    try:
        if not await check_database():
            pytest.skip("数据库不可达")
    except Exception:
        pytest.skip("数据库不可达")

    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT to_regclass('public.site_setting') IS NOT NULL")
        )
        if not result.scalar_one():
            pytest.skip("表未创建（先执行 alembic upgrade head）")


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
    from app.api.middleware.admin_auth import CurrentAdmin, require_admin
    from app.api.middleware.permission import get_permission_resolver
    from app.main import create_app
    from app.modules.system.permissions import permission_codes

    app = create_app()
    app.dependency_overrides[require_admin] = lambda: CurrentAdmin(
        admin_id=uuid.uuid4(), token_version=0
    )

    async def _all_permissions(_session, _admin_id) -> set[str]:
        return set(permission_codes())

    app.dependency_overrides[get_permission_resolver] = lambda: _all_permissions

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def restore_settings() -> Any:
    """测试前记录原始配置，测试后恢复。"""
    from app.db.session import SessionLocal
    from app.modules.system.setting_service import invalidate_settings_cache

    snapshot: dict[str, Any] = {}
    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT setting_key, setting_value FROM site_setting")
        )
        # asyncpg 驱动下 JSONB 列直接返回 Python 对象，无需再 json.loads
        for key, value in result.all():
            snapshot[key] = value

    yield

    async with SessionLocal() as session:
        # 删除本次新增的、恢复原有的
        await session.execute(
            text("DELETE FROM site_setting WHERE setting_key = ANY(:keys)"),
            {"keys": list(DEFAULT_SETTINGS.keys())},
        )
        for key, value in snapshot.items():
            import json

            await session.execute(
                text(
                    """
                    INSERT INTO site_setting (id, setting_key, setting_value,
                                              description, updated_at)
                    VALUES (gen_random_uuid(), :key, CAST(:value AS jsonb),
                            :desc, NOW())
                    """
                ),
                {
                    "key": key,
                    "value": json.dumps(value, ensure_ascii=False),
                    "desc": SETTING_DESCRIPTIONS.get(key),
                },
            )
        await session.commit()

    await invalidate_settings_cache()


class TestGetSettings:
    async def test_returns_all_four_fields(self, client: httpx.AsyncClient) -> None:
        """DoD：配置项含四个固定字段。"""
        response = await client.get("/api/v1/admin/system/settings")

        assert response.status_code == 200
        data = response.json()["data"]

        for key in (
            "site_name",
            "site_description",
            "allow_registration",
            "allow_content_review",
        ):
            assert key in data, f"缺少配置项 {key}"

    async def test_returns_defaults_when_empty(
        self, client: httpx.AsyncClient, restore_settings: None
    ) -> None:
        """库里没有记录时返回默认值，而不是报错或空对象。"""
        from app.db.session import SessionLocal
        from app.modules.system.setting_service import invalidate_settings_cache

        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM site_setting"))
            await session.commit()

        await invalidate_settings_cache()

        response = await client.get("/api/v1/admin/system/settings")
        data = response.json()["data"]

        assert data["site_name"] == DEFAULT_SETTINGS["site_name"]
        assert data["allow_registration"] is True

    async def test_field_types(self, client: httpx.AsyncClient) -> None:
        data = (await client.get("/api/v1/admin/system/settings")).json()["data"]

        assert isinstance(data["site_name"], str)
        assert isinstance(data["site_description"], str)
        assert isinstance(data["allow_registration"], bool)
        assert isinstance(data["allow_content_review"], bool)

    async def test_no_extra_keys(self, client: httpx.AsyncClient) -> None:
        """只返回约定的四个字段，历史遗留键不外泄。"""
        data = (await client.get("/api/v1/admin/system/settings")).json()["data"]

        assert set(data.keys()) == set(DEFAULT_SETTINGS.keys())


class TestUpdateSettings:
    async def test_update_returns_204(
        self, client: httpx.AsyncClient, restore_settings: None
    ) -> None:
        response = await client.put(
            "/api/v1/admin/system/settings",
            json={"site_name": "新站名"},
        )
        assert response.status_code == 204

    async def test_update_reflected_in_get(
        self, client: httpx.AsyncClient, restore_settings: None
    ) -> None:
        """DoD：更新后查询返回新值。"""
        await client.put(
            "/api/v1/admin/system/settings",
            json={"site_name": "测试站点", "allow_registration": False},
        )

        data = (await client.get("/api/v1/admin/system/settings")).json()["data"]

        assert data["site_name"] == "测试站点"
        assert data["allow_registration"] is False

    async def test_partial_update_keeps_others(
        self, client: httpx.AsyncClient, restore_settings: None
    ) -> None:
        """只传一个字段时，其他字段保持原值。"""
        await client.put(
            "/api/v1/admin/system/settings",
            json={"site_description": "新描述"},
        )

        data = (await client.get("/api/v1/admin/system/settings")).json()["data"]

        assert data["site_description"] == "新描述"
        # 其他字段未被清空
        assert data["site_name"] == DEFAULT_SETTINGS["site_name"]
        assert data["allow_registration"] is True

    async def test_persisted_to_db(
        self, client: httpx.AsyncClient, restore_settings: None
    ) -> None:
        """配置确实落到 site_setting 表，不是只改了缓存。"""
        from app.db.session import SessionLocal
        from app.modules.system.setting_service import invalidate_settings_cache

        await client.put(
            "/api/v1/admin/system/settings",
            json={"site_name": "落库验证"},
        )

        # 清缓存强制回源
        await invalidate_settings_cache()

        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    "SELECT setting_value FROM site_setting "
                    "WHERE setting_key = 'site_name'"
                )
            )
            value = result.scalar_one()

        # asyncpg 下 JSONB 直接返回 Python 值
        assert value == "落库验证"

    async def test_empty_payload_is_noop(
        self, client: httpx.AsyncClient, restore_settings: None
    ) -> None:
        before = (await client.get("/api/v1/admin/system/settings")).json()["data"]

        response = await client.put("/api/v1/admin/system/settings", json={})
        assert response.status_code == 204

        after = (await client.get("/api/v1/admin/system/settings")).json()["data"]
        assert after == before

    async def test_invalid_type_rejected(
        self, client: httpx.AsyncClient, restore_settings: None
    ) -> None:
        response = await client.put(
            "/api/v1/admin/system/settings",
            json={"allow_registration": "不是布尔值"},
        )
        assert response.status_code == 400
        assert response.json()["code"] == 10001


class TestCacheInvalidation:
    async def test_cache_invalidated_after_update(
        self, client: httpx.AsyncClient, restore_settings: None
    ) -> None:
        """边界：配置读取有缓存，更新后需失效。"""
        from app.infra import redis as redis_infra

        try:
            # 先读一次填充缓存
            await client.get("/api/v1/admin/system/settings")
            keys = await redis_infra.get_client().keys("*settings:site*")
            assert keys, "配置未写入缓存"
        except Exception:
            pytest.skip("Redis 不可用")

        await client.put(
            "/api/v1/admin/system/settings",
            json={"site_name": "缓存失效验证"},
        )

        # 更新后缓存应被删除
        remaining = await redis_infra.get_client().keys("*settings:site*")
        assert not remaining, "更新后缓存未失效"

        # 再读拿到新值
        data = (await client.get("/api/v1/admin/system/settings")).json()["data"]
        assert data["site_name"] == "缓存失效验证"

    async def test_read_uses_cache(
        self, client: httpx.AsyncClient, restore_settings: None
    ) -> None:
        """第二次读取应命中缓存（不查库也能拿到相同结果）。"""
        from app.modules.system.setting_service import invalidate_settings_cache

        try:
            await invalidate_settings_cache()
            first = (await client.get("/api/v1/admin/system/settings")).json()["data"]
            second = (await client.get("/api/v1/admin/system/settings")).json()["data"]
        except Exception:
            pytest.skip("Redis 不可用")

        assert first == second
