"""M02-T13 景点浏览埋点的测试。

DoD：
    1. 访问详情页产生 ``event_type='view'`` 记录（DB 断言）
    2. ``popularity_stat.view_count`` 递增（DB 断言）
    3. 埋点失败不影响主流程返回（单测：埋点抛异常时接口仍 200）
边界：未登录用户 ``user_id`` 为空仍需记录。
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.modules.recommend.event_recorder import (
    EVENT_CLICK,
    EVENT_GRAPH_VIEW,
    EVENT_VIEW,
    flush_background_tasks,
    record_event,
    record_event_safe,
)

pytestmark = pytest.mark.integration


# ============================================================
# 夹具
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
        for table in ("user_event", "popularity_stat", "attraction"):
            result = await session.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{table}"},
            )
            if not result.scalar_one():
                pytest.skip(f"表 {table} 未创建")


@pytest.fixture
async def client(db_ready: None) -> httpx.AsyncClient:
    from app.main import create_app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    )


@pytest.fixture
async def attraction(db_ready: None) -> Any:
    """造一个已上架的景点，测试后清理相关数据。"""
    from app.db.session import SessionLocal
    from app.utils.ids import uuid7

    suffix = uuid.uuid4().hex[:6]
    city_id = uuid7()
    attraction_id = uuid7()

    async with SessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO region (id, name, level, code, parent_id, heat_score,
                                    sort_weight, created_at, updated_at)
                VALUES (:id, :name, 2, :code, NULL, 0, 100, NOW(), NOW())
                """
            ),
            {
                "id": city_id,
                "name": f"埋点测试市{suffix}",
                "code": f"9{uuid.uuid4().int % 100000:05d}",
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO attraction (id, name, city_id, base_popularity,
                                        is_published, sort_weight, created_at, updated_at)
                VALUES (:id, :name, :cid, 50, TRUE, 0, NOW(), NOW())
                """
            ),
            {"id": attraction_id, "name": f"埋点测试景点{suffix}", "cid": city_id},
        )
        await session.commit()

    yield attraction_id

    async with SessionLocal() as session:
        await session.execute(
            text("DELETE FROM user_event WHERE target_id = :id"),
            {"id": attraction_id},
        )
        await session.execute(
            text("DELETE FROM popularity_stat WHERE attraction_id = :id"),
            {"id": attraction_id},
        )
        await session.execute(
            text("DELETE FROM attraction WHERE id = :id"), {"id": attraction_id}
        )
        await session.execute(text("DELETE FROM region WHERE id = :id"), {"id": city_id})
        await session.commit()


async def _count_events(attraction_id: uuid.UUID, event_type: str) -> int:
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT count(*) FROM user_event "
                "WHERE target_id = :id AND event_type = :type"
            ),
            {"id": attraction_id, "type": event_type},
        )
        return result.scalar_one()


async def _view_count(attraction_id: uuid.UUID) -> int:
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        result = await session.execute(
            text("SELECT view_count FROM popularity_stat WHERE attraction_id = :id"),
            {"id": attraction_id},
        )
        return result.scalar_one_or_none() or 0


# ============================================================
# DoD 1 + 2：详情页产生事件并递增计数
# ============================================================


class TestDetailViewTracking:
    async def test_creates_view_event(
        self, client: httpx.AsyncClient, attraction: uuid.UUID
    ) -> None:
        """DoD：访问详情页产生 ``event_type='view'`` 记录。"""
        before = await _count_events(attraction, EVENT_VIEW)

        async with client:
            response = await client.get(f"/api/v1/attractions/{attraction}")
        assert response.status_code == 200

        # 埋点是后台任务，等它完成
        await flush_background_tasks()

        assert await _count_events(attraction, EVENT_VIEW) == before + 1

    async def test_increments_view_count(
        self, client: httpx.AsyncClient, attraction: uuid.UUID
    ) -> None:
        """DoD：``popularity_stat.view_count`` 递增。"""
        before = await _view_count(attraction)

        async with client:
            await client.get(f"/api/v1/attractions/{attraction}")

        await flush_background_tasks()

        assert await _view_count(attraction) == before + 1

    async def test_multiple_views_accumulate(
        self, client: httpx.AsyncClient, attraction: uuid.UUID
    ) -> None:
        before = await _view_count(attraction)

        async with client:
            for _ in range(3):
                await client.get(f"/api/v1/attractions/{attraction}")

        await flush_background_tasks()

        assert await _view_count(attraction) == before + 3

    async def test_event_has_correct_target(
        self, client: httpx.AsyncClient, attraction: uuid.UUID
    ) -> None:
        from app.db.session import SessionLocal

        async with client:
            await client.get(f"/api/v1/attractions/{attraction}")

        await flush_background_tasks()

        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    "SELECT target_type, target_id, user_id FROM user_event "
                    "WHERE target_id = :id ORDER BY created_at DESC LIMIT 1"
                ),
                {"id": attraction},
            )
            target_type, target_id, user_id = result.one()

        assert target_type == "attraction"
        assert target_id == attraction
        assert user_id is None  # 未登录


# ============================================================
# 边界：未登录用户
# ============================================================


class TestAnonymousTracking:
    async def test_anonymous_user_still_recorded(
        self, client: httpx.AsyncClient, attraction: uuid.UUID
    ) -> None:
        """边界：未登录用户 ``user_id`` 为空但仍需记录。

        游客浏览同样反映景点热度，只是不计入个性化推荐。
        """
        before = await _count_events(attraction, EVENT_VIEW)

        async with client:
            # 不带任何认证信息
            await client.get(f"/api/v1/attractions/{attraction}")

        await flush_background_tasks()

        assert await _count_events(attraction, EVENT_VIEW) == before + 1

    async def test_invalid_token_treated_as_anonymous(
        self, client: httpx.AsyncClient, attraction: uuid.UUID
    ) -> None:
        """坏 Token 不能让公开页面变 401——降级为匿名访问。"""
        before = await _count_events(attraction, EVENT_VIEW)

        async with client:
            response = await client.get(
                f"/api/v1/attractions/{attraction}",
                headers={"Authorization": "Bearer invalid-token"},
            )

        assert response.status_code == 200, "公开页面不应因坏 Token 变成 401"

        await flush_background_tasks()
        assert await _count_events(attraction, EVENT_VIEW) == before + 1


# ============================================================
# DoD 3：埋点失败不影响主流程
# ============================================================


class TestFailureIsolation:
    async def test_recorder_failure_does_not_raise(self) -> None:
        """``record_event_safe`` 内部吞掉所有异常。"""

        class BrokenSession:
            async def __aenter__(self):
                raise RuntimeError("模拟数据库故障")

            async def __aexit__(self, *args):
                return False

        import app.modules.recommend.event_recorder as recorder

        original = recorder.SessionLocal
        recorder.SessionLocal = lambda: BrokenSession()  # type: ignore[assignment]

        try:
            # 不抛异常即通过
            record_event_safe(
                event_type=EVENT_VIEW,
                target_type="attraction",
                target_id=uuid.uuid4(),
            )
            # 等后台任务跑完（它会失败，但异常在任务内被捕获）
            import asyncio

            await asyncio.sleep(0.1)
        finally:
            recorder.SessionLocal = original  # type: ignore[assignment]

    async def test_detail_returns_200_when_recorder_fails(
        self, client: httpx.AsyncClient, attraction: uuid.UUID, monkeypatch
    ) -> None:
        """DoD：埋点抛异常时接口仍 200。"""
        import app.modules.recommend.event_recorder as recorder

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("模拟埋点故障")

        monkeypatch.setattr(recorder, "record_attraction_view", _boom)

        async with client:
            response = await client.get(f"/api/v1/attractions/{attraction}")

        assert response.status_code == 200, "埋点故障不应影响详情返回"
        assert response.json()["code"] == 0


# ============================================================
# 其他事件类型
# ============================================================


class TestOtherEvents:
    async def test_click_event(self, db_ready: None) -> None:
        from app.db.session import SessionLocal
        from app.utils.ids import uuid7

        attraction_id = uuid7()
        async with SessionLocal() as session:
            await record_event(
                session,
                event_type=EVENT_CLICK,
                target_type="attraction",
                target_id=attraction_id,
            )

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT count(*) FROM user_event WHERE target_id = :id"),
                {"id": attraction_id},
            )
            assert result.scalar_one() == 1
            await session.execute(
                text("DELETE FROM user_event WHERE target_id = :id"),
                {"id": attraction_id},
            )
            await session.execute(
                text("DELETE FROM popularity_stat WHERE attraction_id = :id"),
                {"id": attraction_id},
            )
            await session.commit()

    async def test_graph_view_does_not_increment_counter(
        self, db_ready: None
    ) -> None:
        """``graph_view`` 只记事件，不累加计数——它不是热度因子。"""
        from app.db.session import SessionLocal
        from app.utils.ids import uuid7

        attraction_id = uuid7()
        async with SessionLocal() as session:
            await record_event(
                session,
                event_type=EVENT_GRAPH_VIEW,
                target_type="attraction",
                target_id=attraction_id,
            )

        async with SessionLocal() as session:
            result = await session.execute(
                text("SELECT count(*) FROM popularity_stat WHERE attraction_id = :id"),
                {"id": attraction_id},
            )
            assert result.scalar_one() == 0

            await session.execute(
                text("DELETE FROM user_event WHERE target_id = :id"),
                {"id": attraction_id},
            )
            await session.commit()

    async def test_counter_row_created_if_missing(self, db_ready: None) -> None:
        """景点还没有统计行时，第一次浏览要能创建它。"""
        from app.db.session import SessionLocal
        from app.utils.ids import uuid7

        attraction_id = uuid7()
        async with SessionLocal() as session:
            await record_event(
                session,
                event_type=EVENT_VIEW,
                target_type="attraction",
                target_id=attraction_id,
            )

        async with SessionLocal() as session:
            result = await session.execute(
                text(
                    "SELECT view_count FROM popularity_stat WHERE attraction_id = :id"
                ),
                {"id": attraction_id},
            )
            assert result.scalar_one() == 1

            await session.execute(
                text("DELETE FROM user_event WHERE target_id = :id"),
                {"id": attraction_id},
            )
            await session.execute(
                text("DELETE FROM popularity_stat WHERE attraction_id = :id"),
                {"id": attraction_id},
            )
            await session.commit()
