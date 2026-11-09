"""B 端基础数据路由（API §12.1 ~ §12.36）。

全部需 B 端 Token（`require_admin`）。
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.middleware.admin_auth import CurrentAdmin
from app.api.middleware.permission import require_permission
from app.core.deps import DBSession
from app.core.response import success
from app.modules.catalog import service
from app.modules.catalog.schemas import (
    ActivityCreate,
    ActivityPublishRequest,
    ActivityUpdate,
    AttractionCategorySetRequest,
    AttractionCreate,
    AttractionUpdate,
    CategoryCreate,
    CategoryUpdate,
    HotelCreate,
    HotelUpdate,
    RegionCreate,
    RegionUpdate,
    RestaurantCreate,
    RestaurantUpdate,
    TransportCreate,
)
from app.schemas.pagination import PageQuery, page_params

logger = logging.getLogger(__name__)

router = APIRouter()

# ---- 权限依赖别名 ----
# 用模块级 Annotated 别名而不是内联 Annotated[...]，
# 因为本模块有 `from __future__ import annotations`，
# 内联写法会被字符串化，FastAPI 无法在字符串里求值函数调用。
AdminCatalogActivityDelete = Annotated[CurrentAdmin, Depends(require_permission("catalog.activity.delete"))]
AdminCatalogActivityManage = Annotated[CurrentAdmin, Depends(require_permission("catalog.activity.manage"))]
AdminCatalogActivityRead = Annotated[CurrentAdmin, Depends(require_permission("catalog.activity.read"))]
AdminCatalogActivityUpdate = Annotated[CurrentAdmin, Depends(require_permission("catalog.activity.update"))]
AdminCatalogAttractionCreate = Annotated[CurrentAdmin, Depends(require_permission("catalog.attraction.create"))]
AdminCatalogAttractionDelete = Annotated[CurrentAdmin, Depends(require_permission("catalog.attraction.delete"))]
AdminCatalogAttractionRead = Annotated[CurrentAdmin, Depends(require_permission("catalog.attraction.read"))]
AdminCatalogAttractionUpdate = Annotated[CurrentAdmin, Depends(require_permission("catalog.attraction.update"))]
AdminCatalogCategoryCreate = Annotated[CurrentAdmin, Depends(require_permission("catalog.category.create"))]
AdminCatalogCategoryDelete = Annotated[CurrentAdmin, Depends(require_permission("catalog.category.delete"))]
AdminCatalogCategoryRead = Annotated[CurrentAdmin, Depends(require_permission("catalog.category.read"))]
AdminCatalogCategoryUpdate = Annotated[CurrentAdmin, Depends(require_permission("catalog.category.update"))]
AdminCatalogHotelCreate = Annotated[CurrentAdmin, Depends(require_permission("catalog.hotel.create"))]
AdminCatalogHotelDelete = Annotated[CurrentAdmin, Depends(require_permission("catalog.hotel.delete"))]
AdminCatalogHotelRead = Annotated[CurrentAdmin, Depends(require_permission("catalog.hotel.read"))]
AdminCatalogHotelUpdate = Annotated[CurrentAdmin, Depends(require_permission("catalog.hotel.update"))]
AdminCatalogRegionCreate = Annotated[CurrentAdmin, Depends(require_permission("catalog.region.create"))]
AdminCatalogRegionDelete = Annotated[CurrentAdmin, Depends(require_permission("catalog.region.delete"))]
AdminCatalogRegionRead = Annotated[CurrentAdmin, Depends(require_permission("catalog.region.read"))]
AdminCatalogRegionUpdate = Annotated[CurrentAdmin, Depends(require_permission("catalog.region.update"))]
AdminCatalogRestaurantCreate = Annotated[CurrentAdmin, Depends(require_permission("catalog.restaurant.create"))]
AdminCatalogRestaurantDelete = Annotated[CurrentAdmin, Depends(require_permission("catalog.restaurant.delete"))]
AdminCatalogRestaurantRead = Annotated[CurrentAdmin, Depends(require_permission("catalog.restaurant.read"))]
AdminCatalogRestaurantUpdate = Annotated[CurrentAdmin, Depends(require_permission("catalog.restaurant.update"))]
AdminCatalogTransportCreate = Annotated[CurrentAdmin, Depends(require_permission("catalog.transport.create"))]
AdminCatalogTransportDelete = Annotated[CurrentAdmin, Depends(require_permission("catalog.transport.delete"))]
AdminCatalogTransportRead = Annotated[CurrentAdmin, Depends(require_permission("catalog.transport.read"))]


def _serialize(obj: object) -> dict:
    """ORM 对象 → dict。用于创建/更新后返回完整记录。"""
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(obj).mapper
    return {attr.key: getattr(obj, attr.key) for attr in mapper.column_attrs}


# ============================================================
# 省份
# ============================================================


@router.get("/regions/provinces", summary="省份列表", response_model=None)
async def list_provinces(
    _: AdminCatalogRegionRead,
    session: DBSession,
    keyword: Annotated[str | None, Query(max_length=50)] = None,
) -> dict[str, object]:
    """省份列表（API §12.1）。含 ``city_count``。"""
    return success(await service.list_provinces(session, keyword=keyword))


@router.post(
    "/regions/provinces",
    summary="创建省份",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def create_province(
    payload: RegionCreate,
    _: AdminCatalogRegionCreate,
    session: DBSession,
) -> dict[str, object]:
    """创建省份（API §12.2）。``code`` 重复返回 21001。"""
    region = await service.create_region(session, payload=payload, is_province=True)
    return success(_serialize(region))


@router.put(
    "/regions/provinces/{province_id}",
    summary="更新省份",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_province(
    province_id: uuid.UUID,
    payload: RegionUpdate,
    _: AdminCatalogRegionUpdate,
    session: DBSession,
) -> Response:
    """更新省份（API §12.3）。"""
    await service.update_region(
        session, region_id=province_id, payload=payload, is_province=True
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/regions/provinces/{province_id}",
    summary="删除省份",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_province(
    province_id: uuid.UUID,
    _: AdminCatalogRegionDelete,
    session: DBSession,
) -> Response:
    """删除省份（API §12.4）。有下级城市返回 21002。"""
    await service.delete_region(session, region_id=province_id, is_province=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# 城市
# ============================================================


@router.get("/regions/cities", summary="城市列表", response_model=None)
async def list_cities(
    _: AdminCatalogRegionRead,
    session: DBSession,
    paging: Annotated[PageQuery, Depends(page_params)],
    province_id: Annotated[uuid.UUID | None, Query()] = None,
    keyword: Annotated[str | None, Query(max_length=50)] = None,
) -> dict[str, object]:
    """城市列表（API §12.5）。"""
    return success(
        await service.list_cities(
            session,
            province_id=province_id,
            keyword=keyword,
            page=paging.page,
            page_size=paging.page_size,
        )
    )


@router.post(
    "/regions/cities",
    summary="创建城市",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def create_city(
    payload: RegionCreate,
    _: AdminCatalogRegionCreate,
    session: DBSession,
) -> dict[str, object]:
    """创建城市（API §12.6）。``parent_id`` 必填。"""
    region = await service.create_region(session, payload=payload, is_province=False)
    return success(_serialize(region))


@router.put(
    "/regions/cities/{city_id}",
    summary="更新城市",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_city(
    city_id: uuid.UUID,
    payload: RegionUpdate,
    _: AdminCatalogRegionUpdate,
    session: DBSession,
) -> Response:
    await service.update_region(
        session, region_id=city_id, payload=payload, is_province=False
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/regions/cities/{city_id}",
    summary="删除城市",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_city(
    city_id: uuid.UUID,
    _: AdminCatalogRegionDelete,
    session: DBSession,
) -> Response:
    """删除城市（API §12.8）。有景点/餐厅/酒店引用返回 21003。"""
    await service.delete_region(session, region_id=city_id, is_province=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# 分类
# ============================================================


@router.get("/attraction-categories", summary="分类列表", response_model=None)
async def list_categories(
    _: AdminCatalogCategoryRead,
    session: DBSession,
    category_type: Annotated[str | None, Query(pattern="^(theme|level)$")] = None,
) -> dict[str, object]:
    """分类列表（API §12.9）。含每个分类的景点数。"""
    return success(await service.list_categories(session, category_type=category_type))


@router.post(
    "/attraction-categories",
    summary="创建分类",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def create_category(
    payload: CategoryCreate,
    _: AdminCatalogCategoryCreate,
    session: DBSession,
) -> dict[str, object]:
    category = await service.create_category(session, payload=payload)
    return success(_serialize(category))


@router.put(
    "/attraction-categories/{category_id}",
    summary="更新分类",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_category(
    category_id: uuid.UUID,
    payload: CategoryUpdate,
    _: AdminCatalogCategoryUpdate,
    session: DBSession,
) -> Response:
    await service.update_category(session, category_id=category_id, payload=payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/attraction-categories/{category_id}",
    summary="删除分类",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_category(
    category_id: uuid.UUID,
    _: AdminCatalogCategoryDelete,
    session: DBSession,
) -> Response:
    await service.delete_category(session, category_id=category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# 景点
# ============================================================


@router.get("/attractions", summary="景点列表", response_model=None)
async def list_attractions(
    _: AdminCatalogAttractionRead,
    session: DBSession,
    paging: Annotated[PageQuery, Depends(page_params)],
    city_id: Annotated[uuid.UUID | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    is_published: Annotated[bool | None, Query()] = None,
) -> dict[str, object]:
    return success(
        await service.list_attractions(
            session,
            city_id=city_id,
            category_id=category_id,
            keyword=keyword,
            is_published=is_published,
            page=paging.page,
            page_size=paging.page_size,
        )
    )


@router.get("/attractions/{attraction_id}", summary="景点详情", response_model=None)
async def get_attraction(
    attraction_id: uuid.UUID,
    _: AdminCatalogAttractionRead,
    session: DBSession,
) -> dict[str, object]:
    return success(await service.get_attraction(session, attraction_id=attraction_id))


@router.post(
    "/attractions",
    summary="创建景点",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def create_attraction(
    payload: AttractionCreate,
    _: AdminCatalogAttractionCreate,
    session: DBSession,
) -> dict[str, object]:
    attraction = await service.create_attraction(session, payload=payload)
    return success(_serialize(attraction))


@router.put(
    "/attractions/{attraction_id}",
    summary="更新景点",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_attraction(
    attraction_id: uuid.UUID,
    payload: AttractionUpdate,
    _: AdminCatalogAttractionUpdate,
    session: DBSession,
) -> Response:
    await service.update_attraction(
        session, attraction_id=attraction_id, payload=payload
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/attractions/{attraction_id}/categories",
    summary="设置景点分类（批量替换）",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def set_attraction_categories(
    attraction_id: uuid.UUID,
    payload: AttractionCategorySetRequest,
    _: AdminCatalogAttractionUpdate,
    session: DBSession,
) -> Response:
    """批量设置景点分类（API §12.17.1）。

    **整体替换语义**：以请求体为准，不在其中的关联被删除。空数组清空全部。
    """
    await service.set_attraction_categories(
        session, attraction_id=attraction_id, category_ids=payload.category_ids
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/attractions/{attraction_id}",
    summary="删除景点",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_attraction(
    attraction_id: uuid.UUID,
    _: AdminCatalogAttractionDelete,
    session: DBSession,
) -> Response:
    await service.delete_attraction(session, attraction_id=attraction_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# 餐厅
# ============================================================


@router.get(
    "/restaurants/{restaurant_id}", summary="餐厅详情", response_model=None
)
async def get_restaurant(
    restaurant_id: uuid.UUID,
    _: AdminCatalogRestaurantRead,
    session: DBSession,
) -> dict[str, object]:
    """餐厅详情（API §12.20.1）。

    返回全部可编辑字段供编辑表单回填。列表接口只返回展示字段。
    """
    return success(
        await service.get_restaurant(session, restaurant_id=restaurant_id)
    )


@router.get("/restaurants", summary="餐厅列表", response_model=None)
async def list_restaurants(
    _: AdminCatalogRestaurantRead,
    session: DBSession,
    paging: Annotated[PageQuery, Depends(page_params)],
    city_id: Annotated[uuid.UUID | None, Query()] = None,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    is_published: Annotated[bool | None, Query()] = None,
) -> dict[str, object]:
    return success(
        await service.list_restaurants(
            session,
            city_id=city_id,
            keyword=keyword,
            is_published=is_published,
            page=paging.page,
            page_size=paging.page_size,
        )
    )


@router.post(
    "/restaurants",
    summary="创建餐厅",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def create_restaurant(
    payload: RestaurantCreate,
    _: AdminCatalogRestaurantCreate,
    session: DBSession,
) -> dict[str, object]:
    restaurant = await service.create_restaurant(session, payload=payload)
    return success(_serialize(restaurant))


@router.put(
    "/restaurants/{restaurant_id}",
    summary="更新餐厅",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_restaurant(
    restaurant_id: uuid.UUID,
    payload: RestaurantUpdate,
    _: AdminCatalogRestaurantUpdate,
    session: DBSession,
) -> Response:
    await service.update_restaurant(
        session, restaurant_id=restaurant_id, payload=payload
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/restaurants/{restaurant_id}",
    summary="删除餐厅",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_restaurant(
    restaurant_id: uuid.UUID,
    _: AdminCatalogRestaurantDelete,
    session: DBSession,
) -> Response:
    await service.delete_restaurant(session, restaurant_id=restaurant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# 酒店
# ============================================================


@router.get("/hotels/{hotel_id}", summary="酒店详情", response_model=None)
async def get_hotel(
    hotel_id: uuid.UUID,
    _: AdminCatalogHotelRead,
    session: DBSession,
) -> dict[str, object]:
    """酒店详情（API §12.24.1）。返回全部可编辑字段。"""
    return success(await service.get_hotel(session, hotel_id=hotel_id))


@router.get("/hotels", summary="酒店列表", response_model=None)
async def list_hotels(
    _: AdminCatalogHotelRead,
    session: DBSession,
    paging: Annotated[PageQuery, Depends(page_params)],
    city_id: Annotated[uuid.UUID | None, Query()] = None,
    keyword: Annotated[str | None, Query(max_length=100)] = None,
    is_published: Annotated[bool | None, Query()] = None,
) -> dict[str, object]:
    return success(
        await service.list_hotels(
            session,
            city_id=city_id,
            keyword=keyword,
            is_published=is_published,
            page=paging.page,
            page_size=paging.page_size,
        )
    )


@router.post(
    "/hotels", summary="创建酒店", status_code=status.HTTP_201_CREATED, response_model=None
)
async def create_hotel(
    payload: HotelCreate,
    _: AdminCatalogHotelCreate,
    session: DBSession,
) -> dict[str, object]:
    hotel = await service.create_hotel(session, payload=payload)
    return success(_serialize(hotel))


@router.put(
    "/hotels/{hotel_id}", summary="更新酒店", status_code=status.HTTP_204_NO_CONTENT
)
async def update_hotel(
    hotel_id: uuid.UUID,
    payload: HotelUpdate,
    _: AdminCatalogHotelUpdate,
    session: DBSession,
) -> Response:
    await service.update_hotel(session, hotel_id=hotel_id, payload=payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/hotels/{hotel_id}", summary="删除酒店", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_hotel(
    hotel_id: uuid.UUID,
    _: AdminCatalogHotelDelete,
    session: DBSession,
) -> Response:
    await service.delete_hotel(session, hotel_id=hotel_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# 景区交通
# ============================================================


@router.get("/transports", summary="景区交通列表", response_model=None)
async def list_transports(
    _: AdminCatalogTransportRead,
    session: DBSession,
    attraction_id: Annotated[uuid.UUID, Query(description="所属景点")],
) -> dict[str, object]:
    """景区交通列表（API §12.28）。

    只含景区专属交通（观光车/索道/缆车），城际交通不入库。
    """
    return success(await service.list_transports(session, attraction_id=attraction_id))


@router.post(
    "/transports",
    summary="创建景区交通",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def create_transport(
    payload: TransportCreate,
    _: AdminCatalogTransportCreate,
    session: DBSession,
) -> dict[str, object]:
    """创建景区交通（API §12.29）。"""
    transport = await service.create_transport(session, payload=payload)
    return success(_serialize(transport))


@router.delete(
    "/transports/{transport_id}",
    summary="删除景区交通",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_transport(
    transport_id: uuid.UUID,
    _: AdminCatalogTransportDelete,
    session: DBSession,
) -> Response:
    await service.delete_transport(session, transport_id=transport_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ============================================================
# 活动
# ============================================================


@router.get("/activities/{activity_id}", summary="活动详情", response_model=None)
async def get_activity(
    activity_id: uuid.UUID,
    _: AdminCatalogActivityRead,
    session: DBSession,
) -> dict[str, object]:
    """活动详情（API §12.31.1）。返回全部可编辑字段。"""
    return success(
        await service.get_activity(session, activity_id=activity_id)
    )


@router.get("/activities", summary="活动列表", response_model=None)
async def list_activities(
    _: AdminCatalogActivityRead,
    session: DBSession,
    paging: Annotated[PageQuery, Depends(page_params)],
    city_id: Annotated[uuid.UUID | None, Query()] = None,
    is_published: Annotated[bool | None, Query()] = None,
) -> dict[str, object]:
    return success(
        await service.list_activities(
            session,
            city_id=city_id,
            is_published=is_published,
            page=paging.page,
            page_size=paging.page_size,
        )
    )


@router.post(
    "/activities",
    summary="创建活动",
    status_code=status.HTTP_201_CREATED,
    response_model=None,
)
async def create_activity(
    payload: ActivityCreate,
    current: AdminCatalogActivityManage,
    session: DBSession,
) -> dict[str, object]:
    activity = await service.create_activity(
        session, payload=payload, created_by=current.admin_id
    )
    return success(_serialize(activity))


@router.patch(
    "/activities/{activity_id}/publish",
    summary="活动上下架",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def toggle_activity_publish(
    activity_id: uuid.UUID,
    payload: ActivityPublishRequest,
    _: AdminCatalogActivityManage,
    session: DBSession,
) -> Response:
    """活动上下架（API §12.34）。下架后 C 端不再展示。"""
    await service.set_activity_published(
        session, activity_id=activity_id, is_published=payload.is_published
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/activities/{activity_id}",
    summary="更新活动",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_activity(
    activity_id: uuid.UUID,
    payload: ActivityUpdate,
    _: AdminCatalogActivityUpdate,
    session: DBSession,
) -> Response:
    await service.update_activity(session, activity_id=activity_id, payload=payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/activities/{activity_id}",
    summary="删除活动",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_activity(
    activity_id: uuid.UUID,
    _: AdminCatalogActivityDelete,
    session: DBSession,
) -> Response:
    await service.delete_activity(session, activity_id=activity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
