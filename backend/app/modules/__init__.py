"""业务模块（对应 M01~M17）。

每个模块内部结构（架构 §4.3）：
    router.py      API 路由（可选，也可集中在 api/v1）
    service.py     业务逻辑
    repository.py  数据访问封装
    schemas.py     请求/响应模型
    constants.py   枚举与状态定义

模块清单：
    M01 account           用户与账户
    M02 attraction        景点内容
    M03 chat              对话交互
    M04 trip_plan         旅游计划
    M05 footprint         足迹
    M06 agent             Agent 引擎（含 graph/nodes/tools/context/prompts）
    M07 memory            记忆服务
    M08 retrieval         检索调度
    M09 knowledge_base    知识库
    M10 knowledge_graph   知识图谱
    M11 catalog           基础数据（省市/分类/景点/餐厅/酒店/交通/活动）
    M12 model_gateway     模型管理
    M13 quota             额度服务
    M14 user_ops          用户运营
    M15 system            系统管理
    M16 dashboard         数据看板
    M17 recommend         推荐引擎
"""
