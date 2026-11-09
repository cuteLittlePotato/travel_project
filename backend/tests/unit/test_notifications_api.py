"""M01-T15 通知接口的测试。

覆盖 DoD：
    1. 列表按 created_at 倒序
    2. unread_count 为全部未读数，不受筛选影响
    3. 重复标记已读幂等返回 204
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.exceptions import ErrorCode
from app.infra import redis as redis_infra
from app.main import create_app
from app.modules.account import service, token_service
from app.modules.account.constants import NotificationType, VerifyScene
from app.utils.ids import uuid7

pytestmark = pytest.mark.integration


# ============================================================
# 夹具
# ============================================================


class _FakeRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):  # type: ignore[no-untyped-def]
        if nx and key in self._data:
            return None
        self._data[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if self._data.pop(k, None) is not None:
                n += 1
        return n

    async def incr(self, key: str) -> int:
        v = int(self._data.get(key, "0")) + 1
        self._data[key] = str(v)
        return v

    async def decr(self, key: str) -> int:
        v = int(self._data.get(key, "0")) - 1
        self._data[key] = str(v)
        return v

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def ttl(self, key: str) -> int:
        return 300


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
            text("SELECT to_regclass('public.notification') IS NOT NULL")
        )
        if not result.scalar_one():
            pytest.skip("表未创建（先执行 alembic upgrade head）")


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    client = _FakeRedis()
    monkeypatch.setattr(redis_infra, "get_client", lambda: client)
    monkeypatch.setattr(service.redis_infra, "get_client", lambda: client)
    monkeypatch.setattr(token_service.redis_infra, "get_client", lambda: client)
    from app.modules.account import verification

    monkeypatch.setattr(verification.redis_infra, "get_client", lambda: client)
    return client


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def account(db_ready: None, fake_redis: _FakeRedis) -> Any:
    """创建账号并插入 5 条通知（3 未读 / 2 已读）。"""
    from app.db.session import SessionLocal
    from app.modules.account import verification
    from app.modules.account.models import Notification

    phone = f"139{uuid.uuid4().int % 100000000:08d}"
    await fake_redis.set(
        verification._code_key(VerifyScene.REGISTER, phone), "123456", ex=300
    )

    async with SessionLocal() as session:
        result = await service.register(
            session, target=phone, verify_code_str="123456", password="Passw0rd"
        )

    user_id = result.user_id
    now = datetime.now(UTC)
    notification_ids: list[uuid.UUID] = []

    async with SessionLocal() as session:
        for i in range(5):
            nid = uuid7()
            notification_ids.append(nid)
            session.add(
                Notification(
                    id=nid,
                    user_id=user_id,
                    notification_type=(
                        NotificationType.PLAN_STARTING.value
                        if i % 2 == 0
                        else NotificationType.SYSTEM.value
                    ),
                    title=f"通知 {i}",
                    content=f"内容 {i}",
                    is_read=(i >= 3),  # 后两条已读
                    read_at=(now if i >= 3 else None),
                    created_at=now - timedelta(hours=i),
                )
            )
        await session.commit()

    yield {
        "user_id": user_id,
        "access_token": result.access_token,
        "notification_ids": notification_ids,
    }

    async with SessionLocal() as session:
        await session.execute(
            text("DELETE FROM notification WHERE user_id = :uid"), {"uid": user_id}
        )
        for table in ("user_setting", "user_profile", "oauth_binding"):
            await session.execute(
                text(f"DELETE FROM {table} WHERE user_id = :uid"), {"uid": user_id}
            )
        await session.execute(text('DELETE FROM "user" WHERE id = :uid'), {"uid": user_id})
        await session.commit()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# DoD 1：列表
# ============================================================


class TestListNotifications:
    async def test_returns_five_items(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        response = await client.get(
            "/api/v1/notifications", headers=_auth(account["access_token"])
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total"] == 5
        assert len(data["items"]) == 5

    async def test_sorted_by_created_at_desc(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：按 created_at 倒序。"""
        response = await client.get(
            "/api/v1/notifications", headers=_auth(account["access_token"])
        )
        items = response.json()["data"]["items"]
        timestamps = [item["created_at"] for item in items]
        assert timestamps == sorted(timestamps, reverse=True), "应按时间倒序"

    async def test_item_structure(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """API §3.15 定义的字段。"""
        response = await client.get(
            "/api/v1/notifications", headers=_auth(account["access_token"])
        )
        item = response.json()["data"]["items"][0]
        assert set(item) == {
            "id",
            "notification_type",
            "title",
            "content",
            "related_type",
            "related_id",
            "is_read",
            "read_at",
            "created_at",
        }

    async def test_filter_unread(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        response = await client.get(
            "/api/v1/notifications?is_read=false", headers=_auth(account["access_token"])
        )
        data = response.json()["data"]
        assert data["total"] == 3
        assert all(not item["is_read"] for item in data["items"])

    async def test_filter_read(self, client: httpx.AsyncClient, account: dict) -> None:
        response = await client.get(
            "/api/v1/notifications?is_read=true", headers=_auth(account["access_token"])
        )
        assert response.json()["data"]["total"] == 2

    async def test_filter_by_type(self, client: httpx.AsyncClient, account: dict) -> None:
        response = await client.get(
            "/api/v1/notifications?notification_type=system",
            headers=_auth(account["access_token"]),
        )
        data = response.json()["data"]
        assert all(item["notification_type"] == "system" for item in data["items"])

    async def test_pagination(self, client: httpx.AsyncClient, account: dict) -> None:
        response = await client.get(
            "/api/v1/notifications?page=1&page_size=2",
            headers=_auth(account["access_token"]),
        )
        data = response.json()["data"]
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["total_pages"] == 3


# ============================================================
# DoD 2：unread_count 不受筛选影响
# ============================================================


class TestUnreadCountInList:
    async def test_unread_count_ignores_filter(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：unread_count 为全部未读数，不受筛选条件影响。"""
        # 筛选已读
        response = await client.get(
            "/api/v1/notifications?is_read=true", headers=_auth(account["access_token"])
        )
        data = response.json()["data"]
        assert data["total"] == 2, "筛选结果只有 2 条已读"
        assert data["unread_count"] == 3, "但未读数仍应是全账号的 3"

    async def test_unread_count_ignores_type_filter(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        response = await client.get(
            "/api/v1/notifications?notification_type=system",
            headers=_auth(account["access_token"]),
        )
        assert response.json()["data"]["unread_count"] == 3


# ============================================================
# 未读数接口
# ============================================================


class TestUnreadCount:
    async def test_returns_count(self, client: httpx.AsyncClient, account: dict) -> None:
        response = await client.get(
            "/api/v1/notifications/unread-count", headers=_auth(account["access_token"])
        )
        assert response.status_code == 200
        assert response.json()["data"] == {"count": 3}

    async def test_zero_when_no_notifications(
        self, client: httpx.AsyncClient, fake_redis: _FakeRedis
    ) -> None:
        """没有通知的账号返回 0。"""
        from app.db.session import SessionLocal
        from app.modules.account import verification

        phone = f"139{uuid.uuid4().int % 100000000:08d}"
        await fake_redis.set(
            verification._code_key(VerifyScene.REGISTER, phone), "123456", ex=300
        )
        async with SessionLocal() as session:
            result = await service.register(
                session, target=phone, verify_code_str="123456", password="Passw0rd"
            )

        try:
            response = await client.get(
                "/api/v1/notifications/unread-count",
                headers=_auth(result.access_token),
            )
            assert response.json()["data"]["count"] == 0
        finally:
            async with SessionLocal() as session:
                for table in ("user_setting", "user_profile", "oauth_binding"):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE user_id = :uid"),
                        {"uid": result.user_id},
                    )
                await session.execute(
                    text('DELETE FROM "user" WHERE id = :uid'), {"uid": result.user_id}
                )
                await session.commit()


# ============================================================
# DoD 3：标记已读
# ============================================================


class TestMarkRead:
    async def test_marks_single_read(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        nid = account["notification_ids"][0]  # 未读的
        response = await client.patch(
            f"/api/v1/notifications/{nid}/read",
            headers=_auth(account["access_token"]),
        )
        assert response.status_code == 204

        # 未读数从 3 减为 2
        count = await client.get(
            "/api/v1/notifications/unread-count", headers=_auth(account["access_token"])
        )
        assert count.json()["data"]["count"] == 2

    async def test_repeat_mark_is_idempotent(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """DoD：重复标记已读幂等返回 204。"""
        nid = account["notification_ids"][0]

        first = await client.patch(
            f"/api/v1/notifications/{nid}/read", headers=_auth(account["access_token"])
        )
        assert first.status_code == 204

        second = await client.patch(
            f"/api/v1/notifications/{nid}/read", headers=_auth(account["access_token"])
        )
        assert second.status_code == 204, "重复标记应仍返回 204"

    async def test_read_at_not_overwritten(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """幂等性：重复标记不更新 read_at（保留首次阅读时间）。"""
        from app.db.session import SessionLocal

        nid = account["notification_ids"][0]
        await client.patch(
            f"/api/v1/notifications/{nid}/read", headers=_auth(account["access_token"])
        )

        async with SessionLocal() as session:
            first = await session.execute(
                text("SELECT read_at FROM notification WHERE id = :nid"), {"nid": nid}
            )
            first_read_at = first.scalar_one()

        await client.patch(
            f"/api/v1/notifications/{nid}/read", headers=_auth(account["access_token"])
        )

        async with SessionLocal() as session:
            second = await session.execute(
                text("SELECT read_at FROM notification WHERE id = :nid"), {"nid": nid}
            )
            second_read_at = second.scalar_one()

        assert first_read_at == second_read_at

    async def test_other_users_notification_returns_404(
        self, client: httpx.AsyncClient, account: dict, fake_redis: _FakeRedis
    ) -> None:
        """边界：通知不属于当前用户时返回 404。"""
        from app.db.session import SessionLocal
        from app.modules.account import verification

        # 另一个账号
        other_phone = f"139{uuid.uuid4().int % 100000000:08d}"
        await fake_redis.set(
            verification._code_key(VerifyScene.REGISTER, other_phone), "123456", ex=300
        )
        async with SessionLocal() as session:
            other = await service.register(
                session, target=other_phone, verify_code_str="123456", password="Passw0rd"
            )

        try:
            # 用 B 的 Token 标记 A 的通知
            response = await client.patch(
                f"/api/v1/notifications/{account['notification_ids'][0]}/read",
                headers=_auth(other.access_token),
            )
            assert response.status_code == 404
            assert response.json()["code"] == ErrorCode.NOTIFICATION_NOT_FOUND
        finally:
            async with SessionLocal() as session:
                for table in ("user_setting", "user_profile", "oauth_binding"):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE user_id = :uid"),
                        {"uid": other.user_id},
                    )
                await session.execute(
                    text('DELETE FROM "user" WHERE id = :uid'), {"uid": other.user_id}
                )
                await session.commit()

    async def test_nonexistent_id_returns_404(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        response = await client.patch(
            f"/api/v1/notifications/{uuid.uuid4()}/read",
            headers=_auth(account["access_token"]),
        )
        assert response.status_code == 404


# ============================================================
# 全部已读
# ============================================================


class TestReadAll:
    async def test_marks_all_read(self, client: httpx.AsyncClient, account: dict) -> None:
        response = await client.post(
            "/api/v1/notifications/read-all", headers=_auth(account["access_token"])
        )
        assert response.status_code == 200
        assert response.json()["data"]["updated_count"] == 3, "只更新未读的 3 条"

        count = await client.get(
            "/api/v1/notifications/unread-count", headers=_auth(account["access_token"])
        )
        assert count.json()["data"]["count"] == 0

    async def test_second_call_updates_zero(
        self, client: httpx.AsyncClient, account: dict
    ) -> None:
        """重复调用不重复计数。"""
        await client.post(
            "/api/v1/notifications/read-all", headers=_auth(account["access_token"])
        )
        second = await client.post(
            "/api/v1/notifications/read-all", headers=_auth(account["access_token"])
        )
        assert second.json()["data"]["updated_count"] == 0

    async def test_only_affects_own_notifications(
        self, client: httpx.AsyncClient, account: dict, fake_redis: _FakeRedis
    ) -> None:
        """不会误伤他人通知。"""
        from app.db.session import SessionLocal
        from app.modules.account import verification
        from app.modules.account.models import Notification

        other_phone = f"139{uuid.uuid4().int % 100000000:08d}"
        await fake_redis.set(
            verification._code_key(VerifyScene.REGISTER, other_phone), "123456", ex=300
        )
        async with SessionLocal() as session:
            other = await service.register(
                session, target=other_phone, verify_code_str="123456", password="Passw0rd"
            )
            session.add(
                Notification(
                    id=uuid7(),
                    user_id=other.user_id,
                    notification_type=NotificationType.SYSTEM.value,
                    title="他人的通知",
                )
            )
            await session.commit()

        try:
            await client.post(
                "/api/v1/notifications/read-all", headers=_auth(account["access_token"])
            )
            # 他人的仍未读
            other_count = await client.get(
                "/api/v1/notifications/unread-count", headers=_auth(other.access_token)
            )
            assert other_count.json()["data"]["count"] == 1
        finally:
            async with SessionLocal() as session:
                await session.execute(
                    text("DELETE FROM notification WHERE user_id = :uid"),
                    {"uid": other.user_id},
                )
                for table in ("user_setting", "user_profile", "oauth_binding"):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE user_id = :uid"),
                        {"uid": other.user_id},
                    )
                await session.execute(
                    text('DELETE FROM "user" WHERE id = :uid'), {"uid": other.user_id}
                )
                await session.commit()


# ============================================================
# 认证
# ============================================================


class TestAuth:
    async def test_list_requires_auth(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/api/v1/notifications")).status_code == 401

    async def test_unread_requires_auth(self, client: httpx.AsyncClient) -> None:
        assert (await client.get("/api/v1/notifications/unread-count")).status_code == 401

    async def test_mark_requires_auth(self, client: httpx.AsyncClient) -> None:
        response = await client.patch(f"/api/v1/notifications/{uuid.uuid4()}/read")
        assert response.status_code == 401

    async def test_read_all_requires_auth(self, client: httpx.AsyncClient) -> None:
        assert (await client.post("/api/v1/notifications/read-all")).status_code == 401
