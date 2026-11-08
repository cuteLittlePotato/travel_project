"""MinIO 对象存储封装（S3 协议）。

**核心约定（M0-T06 DoD）**：``storage_key`` 是内部实现细节，
**不得直接出现在 API 响应中**，一律转换为预签名 URL 后再返回前端。

理由：
    - 暴露 storage_key 会让前端绕过权限直接构造对象地址
    - 预签名 URL 有有效期，泄露后风险可控
    - 后续从 MinIO 切换到云对象存储时，key 结构变化不会影响前端

路径约定（架构 §1.6 决策 2）：按知识库 ID 组织目录层级，保留原始文件名。
"""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import timedelta
from typing import Any

from app.core.config import settings
from app.infra.exceptions import BucketNotFoundError, ObjectNotFoundError, StorageUnavailableError

logger = logging.getLogger(__name__)


class StorageManager:
    def __init__(self) -> None:
        self._client: Any = None

    # ---------------- 连接 ----------------

    def get_client(self) -> Any:
        if self._client is None:
            from minio import Minio

            self._client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
        return self._client

    async def check(self) -> bool:
        try:
            return await asyncio.to_thread(
                self.get_client().bucket_exists, settings.minio_bucket_documents
            )
        except Exception:
            logger.warning("MinIO 健康检查失败", exc_info=True)
            return False

    def close(self) -> None:
        """释放客户端。

        MinIO SDK 内部使用 urllib3 连接池，没有显式的 close() 方法，
        但部分版本提供 ``_http`` 属性；能关就关，避免连接泄漏告警。
        """
        if self._client is not None:
            http_client = getattr(self._client, "_http", None)
            pool_manager = getattr(http_client, "_pool_manager", None)
            if pool_manager is not None:
                pool_manager.clear()
            self._client = None

    # ---------------- 桶管理 ----------------

    async def ensure_bucket(self, bucket: str | None = None) -> None:
        """桶不存在则创建。启动时或首次上传前调用。"""
        bucket = bucket or settings.minio_bucket_documents
        client = self.get_client()
        try:
            exists = await asyncio.to_thread(client.bucket_exists, bucket)
            if not exists:
                await asyncio.to_thread(client.make_bucket, bucket)
                logger.info("已创建存储桶: %s", bucket)
        except Exception as exc:
            raise StorageUnavailableError(f"创建桶失败：{exc}") from exc

    async def require_bucket(self, bucket: str) -> None:
        try:
            exists = await asyncio.to_thread(self.get_client().bucket_exists, bucket)
        except Exception as exc:
            raise StorageUnavailableError(str(exc)) from exc
        if not exists:
            raise BucketNotFoundError(bucket)

    # ---------------- 对象操作 ----------------

    async def put_object(
        self,
        object_key: str,
        data: bytes | io.IOBase,
        content_type: str = "application/octet-stream",
        bucket: str | None = None,
    ) -> str:
        """上传对象，返回 storage_key（内部使用，**不要直接返回给前端**）。"""
        bucket = bucket or settings.minio_bucket_documents
        payload = io.BytesIO(data) if isinstance(data, bytes) else data
        length = len(data) if isinstance(data, bytes) else _stream_length(data)

        try:
            await asyncio.to_thread(
                self.get_client().put_object,
                bucket,
                object_key,
                payload,
                length,
                content_type=content_type,
            )
        except Exception as exc:
            raise StorageUnavailableError(f"上传失败：{exc}") from exc
        return object_key

    async def get_object(self, object_key: str, bucket: str | None = None) -> bytes:
        bucket = bucket or settings.minio_bucket_documents
        try:
            response = await asyncio.to_thread(
                self.get_client().get_object, bucket, object_key
            )
            try:
                return await asyncio.to_thread(response.read)
            finally:
                response.close()
                response.release_conn()
        except Exception as exc:
            if _is_not_found(exc):
                raise ObjectNotFoundError(object_key) from exc
            raise StorageUnavailableError(f"下载失败：{exc}") from exc

    async def delete_object(self, object_key: str, bucket: str | None = None) -> None:
        bucket = bucket or settings.minio_bucket_documents
        try:
            await asyncio.to_thread(
                self.get_client().remove_object, bucket, object_key
            )
        except Exception as exc:
            raise StorageUnavailableError(f"删除失败：{exc}") from exc

    async def object_exists(self, object_key: str, bucket: str | None = None) -> bool:
        bucket = bucket or settings.minio_bucket_documents
        try:
            await asyncio.to_thread(self.get_client().stat_object, bucket, object_key)
            return True
        except Exception as exc:
            if _is_not_found(exc):
                return False
            raise StorageUnavailableError(f"查询失败：{exc}") from exc

    # ---------------- 预签名 URL ----------------

    def presigned_url(
        self, object_key: str, bucket: str | None = None, expires_seconds: int | None = None
    ) -> str:
        """生成下载用预签名 URL。

        默认有效期 1 小时（配置项 ``MINIO_PRESIGN_EXPIRE_SECONDS``）。
        **API 响应中返回对象的存储位置时，一律用本方法的结果。**
        """
        bucket = bucket or settings.minio_bucket_documents
        expires = expires_seconds or settings.minio_presign_expire_seconds
        try:
            return self.get_client().presigned_get_object(
                bucket, object_key, expires=timedelta(seconds=expires)
            )
        except Exception as exc:
            raise StorageUnavailableError(f"生成预签名 URL 失败：{exc}") from exc

    def presigned_upload_url(
        self, object_key: str, bucket: str | None = None, expires_seconds: int | None = None
    ) -> str:
        """生成直传用预签名 URL，前端可绕过服务端直接上传大文件。"""
        bucket = bucket or settings.minio_bucket_documents
        expires = expires_seconds or settings.minio_presign_expire_seconds
        try:
            return self.get_client().presigned_put_object(
                bucket, object_key, expires=timedelta(seconds=expires)
            )
        except Exception as exc:
            raise StorageUnavailableError(f"生成上传 URL 失败：{exc}") from exc


def _stream_length(stream: io.IOBase) -> int:
    """计算流长度，用于 put_object 的 length 参数。"""
    current = stream.tell()
    stream.seek(0, io.SEEK_END)
    length = stream.tell()
    stream.seek(current)
    return length


def _is_not_found(exc: Exception) -> bool:
    """MinIO 的「对象不存在」表现为 S3Error，错误码 NoSuchKey。"""
    code = getattr(exc, "code", None)
    return code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}


storage_manager = StorageManager()
