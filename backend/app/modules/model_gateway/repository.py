"""M12 模型管理的数据访问层。

只做数据操作，不含业务规则（架构 §4.3）。Repository **不 commit**，
只 flush——事务边界在 service 层。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.model_gateway.models import Model


class ModelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------------- 查询 ----------------

    async def get_by_id(self, model_id: uuid.UUID) -> Model | None:
        return await self.session.get(Model, model_id)

    async def exists_same(
        self,
        *,
        category: str,
        model_code: str,
        base_url: str,
        exclude_id: uuid.UUID | None = None,
    ) -> bool:
        """同类别下 ``model_code + base_url`` 是否已存在。"""
        stmt = (
            select(func.count())
            .select_from(Model)
            .where(
                Model.category == category,
                Model.model_code == model_code,
                Model.base_url == base_url,
            )
        )
        if exclude_id is not None:
            stmt = stmt.where(Model.id != exclude_id)
        return (await self.session.execute(stmt)).scalar_one() > 0

    async def list(
        self,
        *,
        category: str | None = None,
        is_enabled: bool | None = None,
        keyword: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Model], int]:
        conditions = []
        if category is not None:
            conditions.append(Model.category == category)
        if is_enabled is not None:
            conditions.append(Model.is_enabled.is_(is_enabled))
        if keyword:
            conditions.append(Model.name.ilike(f"%{keyword}%"))

        stmt = select(Model).where(*conditions)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()

        stmt = (
            stmt.order_by(
                Model.category, Model.is_default.desc(), Model.created_at.desc()
            )
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def get_default_of_category(self, category: str) -> Model | None:
        result = await self.session.execute(
            select(Model).where(
                Model.category == category,
                Model.is_default.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def count_by_category(self, category: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Model).where(Model.category == category)
        )
        return result.scalar_one()

    # ---------------- 写入 ----------------

    def add(self, model: Model) -> Model:
        self.session.add(model)
        return model

    async def clear_default(self, category: str, exclude_id: uuid.UUID | None = None) -> None:
        """取消该类别下所有模型的默认标记。

        **必须在设置新默认之前执行**：``idx_model_default`` 是
        ``WHERE is_default = TRUE`` 的部分唯一索引，同一类别下
        同时存在两个 ``is_default=TRUE`` 会直接违反约束。

        用 ``UPDATE`` 而非「查出实体再改」——后者在并发下
        可能只改到部分行，留下两个默认。
        """
        stmt = update(Model).where(Model.category == category).values(is_default=False)
        if exclude_id is not None:
            stmt = stmt.where(Model.id != exclude_id)
        await self.session.execute(stmt)

    async def delete(self, model: Model) -> None:
        await self.session.delete(model)

    async def flush(self) -> None:
        await self.session.flush()

    # ---------------- 引用检查 ----------------

    async def count_knowledge_base_refs(self, model_id: uuid.UUID) -> int:
        """统计被知识库引用的次数（禁用/删除前检查）。

        检查 ``knowledge_base.embedding_model_id`` 与 ``rerank_model_id``
        两个字段（DoD 明确要求覆盖这两个）。

        **用原生 SQL 而非 ORM 模型**：``knowledge_base`` 属于 M09，
        在 M12 内导入它的模型会形成跨模块耦合（与 catalog 的
        ``count_references`` 同一套做法）。M09 未建表时返回 0。
        """
        from sqlalchemy import text

        try:
            result = await self.session.execute(
                text(
                    "SELECT count(*) FROM knowledge_base "
                    "WHERE embedding_model_id = :mid OR rerank_model_id = :mid"
                ),
                {"mid": model_id},
            )
            return int(result.scalar_one())
        except Exception:
            # 表不存在（M09 未建）时视为无引用
            await self.session.rollback()
            return 0
