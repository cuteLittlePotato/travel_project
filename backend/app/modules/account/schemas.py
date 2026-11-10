"""M01 用户与账户的请求/响应模型。

与 ORM 模型严格分离（架构 §4.3）：
    - ORM 模型定义「数据库长什么样」
    - 本文件的 Schema 定义「接口长什么样」

**敏感字段约束**：``credential``（密码哈希）、``token_version`` 绝不出现在
任何响应 Schema 中。有测试 ``test_account_models.py`` 与
``TestSensitiveFieldsNotExposed`` 守护。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.account.constants import (
    AVATAR_URL_MAX_LENGTH,
    EMAIL_PATTERN,
    NICKNAME_MAX_LENGTH,
    PASSWORD_PATTERN,
    PHONE_PATTERN,
    PROFILE_ARRAY_ITEM_MAX_LENGTH,
    PROFILE_ARRAY_MAX_ITEMS,
    SEASON_ARRAY_MAX_ITEMS,
    VERIFY_CODE_LENGTH,
    BudgetLevel,
    CompanionType,
    Gender,
    VerifyScene,
    Visibility,
)


def _validate_target(value: str) -> str:
    """校验 target 是手机号或邮箱，返回原值。

    不用 ``Union[PhoneNumber, EmailStr]`` 的原因：两者校验失败的报错信息
    对用户不友好（会同时展示两条 Pydantic 错误）。这里统一定制。
    """
    value = value.strip()
    if PHONE_PATTERN.fullmatch(value):
        return value
    if EMAIL_PATTERN.fullmatch(value):
        return value
    raise ValueError("请输入正确的手机号或邮箱")


def _validate_password(value: str) -> str:
    if not PASSWORD_PATTERN.fullmatch(value):
        raise ValueError("密码需 8-32 位，且同时包含字母与数字")
    # bcrypt 只处理前 72 字节，超出会被静默截断
    if len(value.encode("utf-8")) > 72:
        raise ValueError("密码过长")
    return value


# ============================================================
# 验证码
# ============================================================


class SendCodeRequest(BaseModel):
    """发送验证码（API §3.1）。"""

    target: str = Field(description="手机号或邮箱")
    scene: VerifyScene = Field(description="验证码场景")

    @field_validator("target")
    @classmethod
    def _check_target(cls, v: str) -> str:
        return _validate_target(v)


class SendCodeResponse(BaseModel):
    """发送验证码响应。

    **不包含验证码本身**（DoD 要求）。``debug_code`` 仅在非生产环境返回，
    便于本地联调；生产环境该字段恒为 None。
    """

    expires_in: int = Field(description="有效期（秒）")
    debug_code: str | None = Field(
        default=None,
        description="仅开发环境返回，生产环境为 null",
    )


# ============================================================
# 注册
# ============================================================


class RegisterRequest(BaseModel):
    """注册请求（API §3.2）。"""

    target: str = Field(description="手机号或邮箱")
    verify_code: str = Field(
        min_length=VERIFY_CODE_LENGTH,
        max_length=VERIFY_CODE_LENGTH,
        description="6 位数字验证码",
    )
    #: **注册不设密码**（需求 2.1.1 只要求验证码注册）。
    #: 用户可在「个人中心 → 修改密码」中设置密码，之后即可用密码登录。
    nickname: str | None = Field(
        default=None, max_length=NICKNAME_MAX_LENGTH, description="昵称，默认取 target 前缀"
    )

    @field_validator("target")
    @classmethod
    def _check_target(cls, v: str) -> str:
        return _validate_target(v)

    @field_validator("verify_code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("验证码必须为数字")
        return v

    @field_validator("nickname")
    @classmethod
    def _check_nickname(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        return v


class LoginRequest(BaseModel):
    """密码登录（API §3.3）。

    ``target`` 可以是手机号、邮箱或用户名，三种都支持，
    因此这里**不做格式校验**——用户名可能是任意字符串。
    格式判断在 service 层按查询结果自然区分。
    """

    target: str = Field(min_length=1, max_length=200, description="手机号、邮箱或用户名")
    password: str = Field(min_length=1, max_length=72, description="密码")

    @field_validator("target", "password")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v


class CodeLoginRequest(BaseModel):
    """验证码登录（API §3.4）。"""

    target: str = Field(description="手机号或邮箱")
    verify_code: str = Field(
        min_length=VERIFY_CODE_LENGTH,
        max_length=VERIFY_CODE_LENGTH,
        description="6 位数字验证码",
    )

    @field_validator("target")
    @classmethod
    def _check_target(cls, v: str) -> str:
        return _validate_target(v)

    @field_validator("verify_code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        if not v.isdigit():
            raise ValueError("验证码必须为数字")
        return v


class CodeLoginResponse(BaseModel):
    """验证码登录响应（API §3.4）。

    比密码登录多一个 ``is_new_user``，前端据此决定是否展示新手引导。
    """

    user_id: uuid.UUID
    access_token: str
    refresh_token: str
    expires_in: int
    is_new_user: bool


class OAuthLoginRequest(BaseModel):
    """第三方登录（API §3.5）。

    ``state`` 由前端生成与校验，后端只透传记录（2026-11-08 确认）。
    """

    provider: Literal["wechat", "alipay", "weibo"] = Field(description="服务商")
    code: str = Field(min_length=1, max_length=500, description="第三方授权码")
    state: str = Field(min_length=1, max_length=200, description="防 CSRF 随机串")


class RefreshRequest(BaseModel):
    """刷新 Token 请求（API §3.6）。

    ``refresh_token`` 可选：浏览器场景从 httpOnly Cookie 读取（评审 §Q1），
    非浏览器客户端（小程序、桌面端）从请求体传。
    路由层优先用请求体，为空时回退到 Cookie。
    """

    refresh_token: str | None = Field(
        default=None, max_length=2000, description="刷新令牌，浏览器可省略（走 Cookie）"
    )


class RefreshResponse(BaseModel):
    """刷新响应（API §3.6）。不含 user_id，前端已有。"""

    access_token: str
    refresh_token: str
    expires_in: int


class DeactivateAccountRequest(BaseModel):
    """注销账号（API §3.19）。

    必须提供密码做身份验证——注销是不可逆的破坏性操作，
    不能仅凭一个可能被盗用的 Access Token 执行。
    未设置密码的账号请先设置密码。
    """

    password: str = Field(min_length=1, max_length=72, description="当前密码")
    #: 前端要求用户手动输入「注销」二字，防误触。
    #: 后端也校验，避免绕过前端直接调接口。
    confirmation: str = Field(
        description="必须为「注销」，用于二次确认",
    )

    @field_validator("confirmation")
    @classmethod
    def _check_confirmation(cls, v: str) -> str:
        if v.strip() != "注销":
            raise ValueError("请输入「注销」以确认")
        return v


class ChangePasswordRequest(BaseModel):
    """修改密码（API §3.10）。

    ``old_password`` 可选：自动注册/第三方登录创建的账号没有密码，
    首次设置时不需要提供原密码（2026-11-08 确认）。
    已有密码的账号必须提供。
    """

    old_password: str | None = Field(
        default=None, max_length=72, description="原密码，无密码账号可不传"
    )
    new_password: str = Field(
        min_length=8, max_length=32, description="8-32 位，含字母与数字"
    )

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return _validate_password(v)


class AuthTokenResponse(BaseModel):
    """登录/注册成功后的响应（API §3.2）。

    注意：``refresh_token`` 同时会写入 httpOnly Cookie（评审 §Q1），
    响应体中也返回一份，兼容非浏览器客户端（如小程序）。

    ``token_type`` 不对外暴露——固定为 bearer，前端无需判断。
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID = Field(description="用户 ID")
    access_token: str = Field(description="Access Token，有效期 30 分钟")
    refresh_token: str = Field(description="Refresh Token，有效期 7 天")
    expires_in: int = Field(description="Access Token 有效期（秒）")


# ============================================================
# 用户资料
# ============================================================


class BindingResponse(BaseModel):
    """登录方式绑定（API §3.8）。

    ``provider_uid`` 必须已脱敏——service 层负责调用 ``mask_provider_uid()``。
    """

    provider: str
    provider_uid: str
    is_primary: bool


class UserProfileResponse(BaseModel):
    """当前用户资料（API §3.8）。

    **不含** ``token_version``（内部状态）、``credential``（密码哈希）。
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    nickname: str
    avatar_url: str | None = None
    gender: Gender | None = None
    region_code: str | None = None
    status: str
    created_at: datetime
    bindings: list[BindingResponse] = Field(default_factory=list)


class UpdateAvatarRequest(BaseModel):
    """头像更新（单独接口时使用）。"""

    avatar_url: str = Field(max_length=AVATAR_URL_MAX_LENGTH)

    @field_validator("avatar_url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("头像地址必须以 http:// 或 https:// 开头")
        return v


class UpdateProfileRequest(BaseModel):
    """更新用户资料（API §3.9）。所有字段可选，只更新传入的。"""

    nickname: str | None = Field(default=None, min_length=1, max_length=NICKNAME_MAX_LENGTH)
    avatar_url: str | None = Field(default=None, max_length=AVATAR_URL_MAX_LENGTH)
    gender: Gender | None = None
    region_code: str | None = Field(default=None, max_length=20)

    @field_validator("avatar_url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.startswith(("http://", "https://")):
            raise ValueError("头像地址必须以 http:// 或 https:// 开头")
        return v


# ============================================================
# 偏好与隐私设置
# ============================================================


class TravelProfileResponse(BaseModel):
    """旅游偏好（API §3.11）。"""

    model_config = ConfigDict(from_attributes=True)

    travel_types: list[str] = Field(default_factory=list)
    travel_styles: list[str] = Field(default_factory=list)
    budget_level: BudgetLevel | None = None
    companion_type: CompanionType | None = None
    preferred_seasons: list[str] = Field(default_factory=list)
    departure_city_code: str | None = Field(
        default=None,
        max_length=20,
        description="出发城市编码（GB/T 2260），如 110100",
    )


def _validate_str_list(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if len(value) > PROFILE_ARRAY_MAX_ITEMS:
        raise ValueError(f"最多 {PROFILE_ARRAY_MAX_ITEMS} 项")
    for item in value:
        if len(item) > PROFILE_ARRAY_ITEM_MAX_LENGTH:
            raise ValueError(f"单项不超过 {PROFILE_ARRAY_ITEM_MAX_LENGTH} 字符")
    return value


class UpdateTravelProfileRequest(BaseModel):
    """更新旅游偏好（API §3.12）。

    **整体替换语义**：请求体中未出现的字段会被重置为 null。
    前端应以「表单整体提交」的方式使用，不能只传想改的字段。
    """

    travel_types: list[str] | None = None
    travel_styles: list[str] | None = None
    budget_level: BudgetLevel | None = None
    companion_type: CompanionType | None = None
    preferred_seasons: list[str] | None = None
    departure_city_code: str | None = Field(
        default=None,
        max_length=20,
        pattern=r"^\d{6}$",
        description="出发城市编码（6 位数字），与 user.region_code 同一套格式",
    )

    @field_validator("travel_types", "travel_styles")
    @classmethod
    def _check_list(cls, v: list[str] | None) -> list[str] | None:
        return _validate_str_list(v)

    @field_validator("preferred_seasons")
    @classmethod
    def _check_seasons(cls, v: list[str] | None) -> list[str] | None:
        """季节最多 4 项（API §3.12 比其他数组更严格）。"""
        if v is None:
            return None
        if len(v) > SEASON_ARRAY_MAX_ITEMS:
            raise ValueError(f"季节最多 {SEASON_ARRAY_MAX_ITEMS} 项")
        for item in v:
            if len(item) > PROFILE_ARRAY_ITEM_MAX_LENGTH:
                raise ValueError(f"单项不超过 {PROFILE_ARRAY_ITEM_MAX_LENGTH} 字符")
        return v


class UserSettingResponse(BaseModel):
    """隐私与通知设置（API §3.13）。"""

    model_config = ConfigDict(from_attributes=True)

    profile_visibility: Visibility
    footprint_visibility: Visibility
    plan_visibility: Visibility
    allow_recommendation: bool
    allow_notification: bool


class UpdateUserSettingRequest(BaseModel):
    """部分更新隐私设置（API §3.14）。

    用 ``model_fields_set`` 区分「未传」与「传了 false」——
    这是 PATCH 语义的核心，不能简单用 ``value is not None`` 判断。
    """

    profile_visibility: Visibility | None = None
    footprint_visibility: Visibility | None = None
    plan_visibility: Visibility | None = None
    allow_recommendation: bool | None = None
    allow_notification: bool | None = None
