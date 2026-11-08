"""M0-T05 JWT 认证与双端隔离的测试。

覆盖 DoD：
    1. 无 Token 访问受保护接口 -> 401 + code=11001
    2. C 端 Token 访问 B 端接口 -> 403（反向同样）
    3. token_version 与数据库不一致 -> 401
    4. 敏感字段不出现在响应模型

边界：Token 过期、签名错误、载荷缺字段、alg=none、Token 类型混用。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.middleware.admin_auth import (
    CurrentAdmin,
    get_admin_token_version_resolver,
    require_admin,
)
from app.api.middleware.auth import (
    CurrentUser,
    get_token_version_resolver,
    require_user,
)
from app.core.config import settings
from app.core.exceptions import ErrorCode
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_token_pair,
    decode_token,
    hash_password,
    verify_password,
    verify_token_version,
)
from app.db.session import get_db
from app.utils.ids import uuid7

# ============================================================
# 测试用应用：C/B 端各一个受保护接口
# ============================================================


def _build_app(user_version: int | None, admin_version: int | None) -> FastAPI:
    from app.core.error_handlers import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    class _FakeSession:
        """认证层只需要一个占位会话；版本号由解析器替身提供。"""

    async def _fake_db() -> Any:
        yield _FakeSession()

    async def _user_version(_session: Any, _user_id: uuid.UUID) -> int | None:
        return user_version

    async def _admin_version(_session: Any, _admin_id: uuid.UUID) -> int | None:
        return admin_version

    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_token_version_resolver] = lambda: _user_version
    app.dependency_overrides[get_admin_token_version_resolver] = lambda: _admin_version

    @app.get("/api/v1/me")
    async def me(current: CurrentUser = Depends(require_user)) -> dict[str, str]:
        return {"user_id": str(current.user_id)}

    @app.get("/api/v1/admin/me")
    async def admin_me(current: CurrentAdmin = Depends(require_admin)) -> dict[str, str]:
        return {"admin_id": str(current.admin_id)}

    return app


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid7()


@pytest.fixture
def app_with_user(user_id: uuid.UUID) -> FastAPI:
    return _build_app(user_version=3, admin_version=0)


@pytest.fixture
def client_with_user(app_with_user: FastAPI) -> TestClient:
    return TestClient(app_with_user, raise_server_exceptions=False)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# DoD 1：无 Token -> 401
# ============================================================


class TestMissingToken:
    def test_c_end_requires_token(self, client_with_user: TestClient) -> None:
        response = client_with_user.get("/api/v1/me")
        assert response.status_code == 401
        assert response.json()["code"] == ErrorCode.UNAUTHORIZED == 11001

    def test_b_end_requires_token(self, client_with_user: TestClient) -> None:
        response = client_with_user.get("/api/v1/admin/me")
        assert response.status_code == 401
        assert response.json()["code"] == 11001

    def test_empty_bearer_rejected(self, client_with_user: TestClient) -> None:
        response = client_with_user.get("/api/v1/me", headers={"Authorization": "Bearer "})
        assert response.status_code == 401

    def test_malformed_header_rejected(self, client_with_user: TestClient) -> None:
        response = client_with_user.get("/api/v1/me", headers={"Authorization": "token"})
        assert response.status_code == 401


# ============================================================
# DoD 2：双端隔离
# ============================================================


class TestCrossEndIsolation:
    def test_c_token_cannot_access_b_end(
        self, client_with_user: TestClient, user_id: uuid.UUID
    ) -> None:
        token = create_access_token(str(user_id), "user", 3)
        response = client_with_user.get("/api/v1/admin/me", headers=_auth(token))
        assert response.status_code == 403
        assert "B 端" in response.json()["message"]

    def test_b_token_cannot_access_c_end(self, client_with_user: TestClient) -> None:
        token = create_access_token(str(uuid7()), "admin", 0)
        response = client_with_user.get("/api/v1/me", headers=_auth(token))
        assert response.status_code == 403
        assert "C 端" in response.json()["message"]

    def test_matching_token_is_accepted(
        self, client_with_user: TestClient, user_id: uuid.UUID
    ) -> None:
        token = create_access_token(str(user_id), "user", 3)
        response = client_with_user.get("/api/v1/me", headers=_auth(token))
        assert response.status_code == 200
        assert response.json()["user_id"] == str(user_id)

    def test_admin_token_accepted_on_b_end(self, client_with_user: TestClient) -> None:
        admin_id = uuid7()
        token = create_access_token(str(admin_id), "admin", 0)
        response = client_with_user.get("/api/v1/admin/me", headers=_auth(token))
        assert response.status_code == 200
        assert response.json()["admin_id"] == str(admin_id)


# ============================================================
# DoD 3：token_version 与数据库比对
# ============================================================


class TestTokenVersion:
    def test_mismatch_returns_401(self) -> None:
        """数据库版本已变（登出/改密/封禁），旧 Token 必须失效。"""
        app = _build_app(user_version=4, admin_version=0)
        client = TestClient(app, raise_server_exceptions=False)
        token = create_access_token(str(uuid7()), "user", 3)

        response = client.get("/api/v1/me", headers=_auth(token))
        assert response.status_code == 401
        assert response.json()["code"] == ErrorCode.UNAUTHORIZED

    def test_account_not_found_returns_401(self) -> None:
        """账号被删除时解析器返回 None，同样视为无效。"""
        app = _build_app(user_version=None, admin_version=0)
        client = TestClient(app, raise_server_exceptions=False)
        token = create_access_token(str(uuid7()), "user", 3)

        response = client.get("/api/v1/me", headers=_auth(token))
        assert response.status_code == 401

    def test_match_passes(self) -> None:
        app = _build_app(user_version=3, admin_version=0)
        client = TestClient(app, raise_server_exceptions=False)
        token = create_access_token(str(uuid7()), "user", 3)
        assert client.get("/api/v1/me", headers=_auth(token)).status_code == 200

    def test_admin_version_mismatch_returns_401(self) -> None:
        app = _build_app(user_version=0, admin_version=5)
        client = TestClient(app, raise_server_exceptions=False)
        token = create_access_token(str(uuid7()), "admin", 4)
        assert client.get("/api/v1/admin/me", headers=_auth(token)).status_code == 401

    def test_verify_token_version_pure_function(self) -> None:
        payload = decode_token(create_access_token(str(uuid7()), "user", 2), "access")
        verify_token_version(payload, 2)  # 不抛异常即通过

        with pytest.raises(Exception, match="已失效"):
            verify_token_version(payload, 3)

        with pytest.raises(Exception, match="账号不存在"):
            verify_token_version(payload, None)

    def test_token_version_incremented_on_logout_invalidates(self) -> None:
        """模拟登出：token_version +1 后旧 Token 失效。"""
        uid = uuid7()
        issued_version = 0
        app = _build_app(user_version=issued_version, admin_version=0)
        client = TestClient(app, raise_server_exceptions=False)
        old_token = create_access_token(str(uid), "user", issued_version)
        assert client.get("/api/v1/me", headers=_auth(old_token)).status_code == 200

        # 登出后版本自增
        app_after = _build_app(user_version=issued_version + 1, admin_version=0)
        client_after = TestClient(app_after, raise_server_exceptions=False)
        assert client_after.get("/api/v1/me", headers=_auth(old_token)).status_code == 401


# ============================================================
# 边界：Token 各类攻击面
# ============================================================


class TestTokenEdgeCases:
    def test_expired_token_rejected(self, client_with_user: TestClient) -> None:
        from datetime import UTC, datetime, timedelta

        expired = jwt.encode(
            {
                "sub": str(uuid7()),
                "user_type": "user",
                "token_version": 3,
                "token_type": "access",
                "exp": int((datetime.now(UTC) - timedelta(minutes=1)).timestamp()),
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        response = client_with_user.get("/api/v1/me", headers=_auth(expired))
        assert response.status_code == 401
        assert "过期" in response.json()["message"]

    def test_wrong_signature_rejected(self, client_with_user: TestClient) -> None:
        forged = jwt.encode(
            {
                "sub": str(uuid7()),
                "user_type": "user",
                "token_version": 3,
                "token_type": "access",
                "exp": 9999999999,
            },
            "a-different-secret-key-at-least-32-chars",
            algorithm="HS256",
        )
        assert client_with_user.get("/api/v1/me", headers=_auth(forged)).status_code == 401

    def test_alg_none_rejected(self, client_with_user: TestClient) -> None:
        """算法混淆攻击：alg=none 必须拒绝。"""
        forged = jwt.encode(
            {
                "sub": str(uuid7()),
                "user_type": "user",
                "token_version": 3,
                "token_type": "access",
                "exp": 9999999999,
            },
            key="",
            algorithm="none",
        )
        response = client_with_user.get("/api/v1/me", headers=_auth(forged))
        assert response.status_code == 401
        assert "算法" in response.json()["message"]

    def test_missing_claim_rejected(self, client_with_user: TestClient) -> None:
        incomplete = jwt.encode(
            {"sub": str(uuid7()), "exp": 9999999999},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        assert client_with_user.get("/api/v1/me", headers=_auth(incomplete)).status_code == 401

    def test_refresh_token_cannot_access_api(self, client_with_user: TestClient) -> None:
        """Refresh Token 只能用于刷新，不能直接访问业务接口。"""
        token = create_refresh_token(str(uuid7()), "user", 3)
        response = client_with_user.get("/api/v1/me", headers=_auth(token))
        assert response.status_code == 401
        assert "类型" in response.json()["message"]

    def test_non_uuid_subject_rejected(self, client_with_user: TestClient) -> None:
        token = create_access_token("not-a-uuid", "user", 3)
        assert client_with_user.get("/api/v1/me", headers=_auth(token)).status_code == 401

    def test_invalid_user_type_rejected(self, client_with_user: TestClient) -> None:
        token = jwt.encode(
            {
                "sub": str(uuid7()),
                "user_type": "superuser",
                "token_version": 0,
                "token_type": "access",
                "exp": 9999999999,
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        assert client_with_user.get("/api/v1/me", headers=_auth(token)).status_code == 401


# ============================================================
# 密码哈希
# ============================================================


class TestPasswordHashing:
    def test_roundtrip(self) -> None:
        hashed = hash_password("Passw0rd!")
        assert hashed != "Passw0rd!"
        assert verify_password("Passw0rd!", hashed)
        assert not verify_password("wrong", hashed)

    def test_hash_is_bcrypt(self) -> None:
        assert hash_password("x").startswith("$2b$")

    def test_over_72_bytes_rejected(self) -> None:
        """bcrypt 会截断超长密码，必须显式拒绝而不是静默截断。"""
        with pytest.raises(ValueError, match="72"):
            hash_password("a" * 73)

    def test_verify_over_72_bytes_fails_without_raising(self) -> None:
        hashed = hash_password("a" * 72)
        assert verify_password("a" * 73, hashed) is False

    def test_malformed_hash_returns_false(self) -> None:
        assert verify_password("x", "not-a-bcrypt-hash") is False


# ============================================================
# Token 签发
# ============================================================


class TestTokenIssuing:
    def test_token_pair_contains_both_tokens(self) -> None:
        pair = create_token_pair(str(uuid7()), "user", 0)
        assert set(pair) == {"access_token", "refresh_token", "token_type", "expires_in"}
        assert pair["token_type"] == "bearer"
        assert pair["expires_in"] == settings.access_token_expire_minutes * 60

    def test_access_and_refresh_have_different_types(self) -> None:
        uid = str(uuid7())
        assert decode_token(create_access_token(uid, "user", 0), "access").token_type == "access"
        assert (
            decode_token(create_refresh_token(uid, "user", 0), "refresh").token_type == "refresh"
        )


# ============================================================
# DoD 4：敏感字段不出现在响应模型
# ============================================================


class TestSensitiveFieldsNotExposed:
    SENSITIVE = ("password_hash", "credential", "api_key", "secret", "token_version")

    def test_schemas_have_no_sensitive_fields(self) -> None:
        """序列化模型不得暴露密码哈希、凭据、密钥等字段。"""
        from pydantic import BaseModel

        from app import schemas

        offenders: list[str] = []
        for name in dir(schemas):
            obj = getattr(schemas, name)
            if not (isinstance(obj, type) and issubclass(obj, BaseModel)):
                continue
            for field_name in obj.model_fields:
                if field_name.lower() in self.SENSITIVE:
                    offenders.append(f"{name}.{field_name}")

        assert not offenders, f"响应模型包含敏感字段: {offenders}"

    def test_auth_response_does_not_leak_password(self) -> None:
        """认证接口的返回体不含 password_hash / credential。"""
        app = _build_app(user_version=0, admin_version=0)
        client = TestClient(app, raise_server_exceptions=False)
        token = create_access_token(str(uuid7()), "user", 0)
        body = client.get("/api/v1/me", headers=_auth(token)).text
        for field in ("password_hash", "credential", "token_version"):
            assert field not in body

    def test_source_has_no_hardcoded_secret(self) -> None:
        """JWT 密钥只能来自配置。"""
        app_dir = Path(__file__).resolve().parents[2] / "app"
        offenders = []
        for path in app_dir.rglob("*.py"):
            if path.name == "config.py":
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "jwt_secret_key =" in line and "settings" not in line:
                    offenders.append(f"{path.name}:{lineno}")
        assert not offenders, offenders
