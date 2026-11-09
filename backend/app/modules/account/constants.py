"""M01 用户与账户的枚举与常量。

与 ``scripts/sql/schema.sql`` 中的 CHECK 约束一一对应。
修改此处必须同步数据库 CHECK 约束（走新迁移），否则写入会被数据库拒绝。

用 ``StrEnum`` 而非普通类：Pydantic 与 SQLAlchemy 都能直接接收，
序列化为字符串，前端拿到的仍是 ``"active"`` 而非 ``"UserStatus.ACTIVE"``。
"""

from __future__ import annotations

import re
from enum import StrEnum


class UserStatus(StrEnum):
    """账号状态（``user.status``）。"""

    ACTIVE = "active"
    """正常。"""

    BANNED = "banned"
    """封禁。所有 Token 失效（``token_version`` 自增）。"""

    DELETED = "deleted"
    """已注销。数据保留但不可登录，Token 一律失效。"""


class Gender(StrEnum):
    """性别（``user.gender``）。"""

    MALE = "male"
    FEMALE = "female"
    SECRET = "secret"
    """保密。默认值缺失时按此处理，不强制用户填写。"""


class BindingProvider(StrEnum):
    """登录方式（``oauth_binding.provider``）。"""

    PHONE = "phone"
    EMAIL = "email"
    WECHAT = "wechat"
    ALIPAY = "alipay"
    WEIBO = "weibo"

    @property
    def is_third_party(self) -> bool:
        """是否为第三方 OAuth（需要 access_token 换取 openid）。

        手机号/邮箱是「凭证直连」：注册时校验验证码，
        第三方则是「授权码换 openid」，错误处理路径不同。
        """
        return self in (BindingProvider.WECHAT, BindingProvider.ALIPAY, BindingProvider.WEIBO)


class BudgetLevel(StrEnum):
    """预算档位（``user_profile.budget_level``）。"""

    ECONOMY = "economy"
    MODERATE = "moderate"
    COMFORTABLE = "comfortable"
    LUXURY = "luxury"


class CompanionType(StrEnum):
    """同行人类型（``user_profile.companion_type``）。"""

    SOLO = "solo"
    COUPLE = "couple"
    FAMILY = "family"
    FRIENDS = "friends"


class Visibility(StrEnum):
    """可见性（``user_setting`` 的三个 visibility 字段）。"""

    PUBLIC = "public"
    FRIENDS = "friends"
    PRIVATE = "private"


class NotificationType(StrEnum):
    """通知类型（``notification.notification_type``）。"""

    PLAN_STARTING = "plan_starting"
    """计划即将开始。"""

    PLAN_ENDED = "plan_ended"
    """计划已结束，引导写足迹。"""

    SYSTEM = "system"
    """系统通知。"""


class VerifyScene(StrEnum):
    """验证码使用场景（Redis key 的一部分）。"""

    REGISTER = "register"
    LOGIN = "login"
    RESET_PASSWORD = "reset_password"


#: 验证码有效期（秒）。需求 §2.1.1：5 分钟。
VERIFY_CODE_TTL_SECONDS = 300

#: 同一目标发送间隔（秒）。需求 §2.1.1：1 分钟/次。
VERIFY_CODE_SEND_INTERVAL_SECONDS = 60

#: 同一目标每日发送上限。需求 §2.1.1：每日 5 次。
VERIFY_CODE_DAILY_LIMIT = 5

#: 验证码长度。
VERIFY_CODE_LENGTH = 6

#: 密码错误锁定阈值：连续 5 次锁定 15 分钟（M01-T05 DoD）。
LOGIN_FAIL_LIMIT = 5
LOGIN_LOCK_SECONDS = 15 * 60

#: 昵称最大长度（``user.nickname`` 为 VARCHAR(50)）。
NICKNAME_MAX_LENGTH = 50

#: 头像 URL 最大长度（``user.avatar_url`` 为 VARCHAR(500)）。
AVATAR_URL_MAX_LENGTH = 500

#: 偏好数组字段的最大项数（M01-T12 DoD）。
PROFILE_ARRAY_MAX_ITEMS = 10

#: 偏好数组单项最大长度（M01-T12 DoD）。
PROFILE_ARRAY_ITEM_MAX_LENGTH = 20

#: 季节数组最大项数（API §3.12：最多 4 项，四季）
SEASON_ARRAY_MAX_ITEMS = 4

# ============================================================
# 格式校验正则（供 schemas 与 verification 共用）
# ============================================================

#: 手机号：中国大陆 11 位，1 开头
PHONE_PATTERN = re.compile(r"^1[3-9]\d{9}$")

#: 邮箱：宽松校验，只拦明显错误的格式。
#: 不引入 email-validator 依赖——服务端最终会用验证码确认邮箱真实性，
#: 正则只需挡住拼写错误。
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

#: 密码：8-32 位，必须同时含字母与数字
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,32}$")
