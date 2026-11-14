"""M15 系统管理的请求/响应模型（API §14.1 ~ §14.5）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: 用户名：字母、数字、下划线，3-50 字符（API §14.2）
USERNAME_PATTERN = r"^[A-Za-z0-9_]{3,50}$"

#: 密码：8-32 位，至少含一个字母和一个数字（API §14.2 / §14.16）
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 32


def _validate_password(value: str) -> str:
    if not (PASSWORD_MIN_LENGTH <= len(value) <= PASSWORD_MAX_LENGTH):
        raise ValueError(f"密码长度需在 {PASSWORD_MIN_LENGTH}-{PASSWORD_MAX_LENGTH} 位之间")
    if not any(ch.isalpha() for ch in value):
        raise ValueError("密码必须包含字母")
    if not any(ch.isdigit() for ch in value):
        raise ValueError("密码必须包含数字")
    return value


class RoleBrief(BaseModel):
    """管理员所属角色（API §14.1 ``roles``）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str


class AdminResponse(BaseModel):
    """管理员列表项 / 详情（API §14.1）。

    **不返回 ``password_hash`` 与 ``token_version``**（DoD）：
    前者是凭据，后者是内部鉴权状态，前端都不需要。
    ``token_version`` 泄露还会让人推断出「这个账号最近被强制下线过」。
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    real_name: str | None
    email: str | None
    status: str
    roles: list[RoleBrief] = Field(default_factory=list)
    last_login_at: datetime | None
    created_at: datetime


class AdminCreate(BaseModel):
    """创建管理员（API §14.2）。"""

    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    real_name: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=100)
    #: 至少一个角色（API §14.2）
    role_ids: list[uuid.UUID] = Field(min_length=1)

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password(value)

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str | None) -> str | None:
        if value and "@" not in value:
            raise ValueError("邮箱格式不正确")
        return value


class AdminUpdate(BaseModel):
    """更新管理员（API §14.3）。

    字段全部可选——PATCH 语义，只改传入的字段。
    ``username`` 不可改：它是登录凭据，改了会让操作日志里
    这个人的历史记录对不上。
    """

    real_name: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=100)
    role_ids: list[uuid.UUID] | None = None
    status: Literal["active", "disabled"] | None = None

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str | None) -> str | None:
        if value and "@" not in value:
            raise ValueError("邮箱格式不正确")
        return value


class AdminPasswordReset(BaseModel):
    """重置管理员密码（API §14.4）。"""

    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password(value)


# ============================================================
# 角色（API §14.6 ~ §14.9，M15-T04 实现）
# ============================================================


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_builtin: bool
    created_at: datetime
    updated_at: datetime

    #: 该角色下的管理员数（删除前的引用提示）
    admin_count: int = 0
    #: 该角色的权限项数
    permission_count: int = 0


class RoleDetail(RoleResponse):
    permissions: list[PermissionBrief] = Field(default_factory=list)


class RoleCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,49}$")
    name: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=200)
    permission_ids: list[uuid.UUID] | None = None


class RoleUpdate(BaseModel):
    """更新角色。

    ``code`` 不可改：代码里按 code 引用内置角色，改编码会让引用失效。
    """

    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=200)


class RolePermissionSet(BaseModel):
    """设置角色权限（整体替换语义）。"""

    permission_ids: list[uuid.UUID]


class PermissionBrief(BaseModel):
    """权限项（API §14.10）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    module: str
    action: str
    name: str
    description: str | None


class AdminRoleAssign(BaseModel):
    """单独调整管理员的角色（API §14.3 的一部分）。"""

    role_ids: list[uuid.UUID]


# ============================================================
# 操作日志（API §14.11，M15-T06 实现）
# ============================================================


class OperationLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    admin_user_id: uuid.UUID
    admin_username: str | None = None
    module: str
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    detail: dict | None
    ip_address: str | None
    user_agent: str | None
    is_success: bool
    created_at: datetime


# ============================================================
# 站点配置（API §14.12 / §14.13，M15-T07 实现）
# ============================================================


class SiteSettingResponse(BaseModel):
    """站点配置（键值对形式）。

    API 文档的响应用的是固定字段（site_name / site_description / ...），
    但数据库存的是键值对。这里两种都提供：固定字段便于前端直接绑定，
    完整字典便于未来扩展配置项而不改接口契约。
    """

    site_name: str = ""
    site_description: str = ""
    allow_registration: bool = True
    allow_content_review: bool = True


class SiteSettingUpdate(BaseModel):
    """更新站点配置（全部可选，只改传入的字段）。"""

    site_name: Annotated[str | None, Field(max_length=100)] = None
    site_description: Annotated[str | None, Field(max_length=500)] = None
    allow_registration: bool | None = None
    allow_content_review: bool | None = None


RoleDetail.model_rebuild()


# ============================================================
# 管理员认证（API §14.14 ~ §14.16）
# ============================================================


class AdminLoginRequest(BaseModel):
    """管理员登录（API §14.14）。"""

    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class AdminInfo(BaseModel):
    """登录响应里的管理员信息。"""

    id: str
    username: str
    real_name: str | None
    roles: list[RoleBrief] = Field(default_factory=list)


class AdminLoginResponse(BaseModel):
    """登录响应（API §14.14，结构同 C 端登录但 ``user_type='admin'``）。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user_type: Literal["admin"] = "admin"
    admin: AdminInfo


class AdminRefreshRequest(BaseModel):
    """刷新请求（非浏览器客户端用；浏览器走 httpOnly Cookie）。"""

    refresh_token: str | None = None


class ChangeOwnPasswordRequest(BaseModel):
    """修改自己的密码（API §14.16）。"""

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password(value)
