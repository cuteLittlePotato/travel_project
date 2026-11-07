-- =============================================================
-- 云游坊 - 数据库建表脚本
-- =============================================================
-- 数据库：PostgreSQL 15+
-- 主键策略：UUIDv7（由应用层生成）
-- 外键策略：不使用物理外键，逻辑关联由应用层维护
-- 时间策略：统一使用 TIMESTAMPTZ（UTC）
-- =============================================================

-- =============================================================
-- 扩展与公共函数
-- =============================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 自动更新 updated_at 的触发器函数
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- =============================================================
-- 3.1 用户与账户（M01）
-- =============================================================

CREATE TABLE user (
    id              UUID PRIMARY KEY,
    username        VARCHAR(50) NOT NULL,
    nickname        VARCHAR(50) NOT NULL,
    avatar_url      VARCHAR(500),
    gender          VARCHAR(10) CHECK (gender IN ('male', 'female', 'secret')),
    region_code     VARCHAR(20),
    status          VARCHAR(20) NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'banned', 'deleted')),
    token_version   INTEGER NOT NULL DEFAULT 0,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_user_username ON user (username);
CREATE INDEX idx_user_status ON user (status);
CREATE INDEX idx_user_created_at ON user (created_at DESC);

COMMENT ON TABLE user IS '用户主表';
COMMENT ON COLUMN user.status IS '账号状态：active=正常，banned=封禁，deleted=已注销';
COMMENT ON COLUMN user.token_version IS 'Token 版本号，登出/改密/封禁时自增，使所有已签发 Token 失效（全端登出）';
COMMENT ON COLUMN user.region_code IS '常驻地区行政区划编码';

CREATE TRIGGER trg_user_updated_at
    BEFORE UPDATE ON user
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE oauth_binding (
    id              UUID PRIMARY KEY,
    user_id         UUID NOT NULL,
    provider        VARCHAR(20) NOT NULL
                    CHECK (provider IN ('phone', 'email', 'wechat', 'alipay', 'weibo')),
    provider_uid    VARCHAR(200) NOT NULL,
    credential      VARCHAR(255),
    extra_data      JSONB,
    is_primary      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_oauth_provider_uid ON oauth_binding (provider, provider_uid);
CREATE INDEX idx_oauth_user_id ON oauth_binding (user_id);

COMMENT ON TABLE oauth_binding IS '登录方式绑定表';
COMMENT ON COLUMN oauth_binding.provider_uid IS '第三方唯一标识：手机号、邮箱、openid 等';
COMMENT ON COLUMN oauth_binding.credential IS '密码哈希，仅 phone/email 方式使用（bcrypt）';


CREATE TABLE user_profile (
    id                  UUID PRIMARY KEY,
    user_id             UUID NOT NULL,
    travel_types        JSONB,
    travel_styles       JSONB,
    budget_level        VARCHAR(20)
                        CHECK (budget_level IN ('economy', 'moderate', 'comfortable', 'luxury')),
    companion_type      VARCHAR(20)
                        CHECK (companion_type IN ('solo', 'couple', 'family', 'friends')),
    preferred_seasons   JSONB,
    departure_city      VARCHAR(50),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_user_profile_user_id ON user_profile (user_id);

COMMENT ON TABLE user_profile IS '用户偏好档案（用户显式设置）';
COMMENT ON COLUMN user_profile.travel_types IS '旅游类型偏好数组，如 ["历史人文","自然风光"]';
COMMENT ON COLUMN user_profile.budget_level IS '预算等级：economy=经济，moderate=中等，comfortable=舒适，luxury=豪华';

CREATE TRIGGER trg_user_profile_updated_at
    BEFORE UPDATE ON user_profile
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE user_setting (
    id                      UUID PRIMARY KEY,
    user_id                 UUID NOT NULL,
    profile_visibility      VARCHAR(20) NOT NULL DEFAULT 'public'
                            CHECK (profile_visibility IN ('public', 'friends', 'private')),
    footprint_visibility    VARCHAR(20) NOT NULL DEFAULT 'public'
                            CHECK (footprint_visibility IN ('public', 'friends', 'private')),
    plan_visibility         VARCHAR(20) NOT NULL DEFAULT 'public'
                            CHECK (plan_visibility IN ('public', 'friends', 'private')),
    allow_recommendation    BOOLEAN NOT NULL DEFAULT TRUE,
    allow_notification      BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_user_setting_user_id ON user_setting (user_id);

COMMENT ON TABLE user_setting IS '用户隐私与通知设置';

CREATE TRIGGER trg_user_setting_updated_at
    BEFORE UPDATE ON user_setting
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


-- =============================================================
-- 3.2 基础数据（M11）
-- =============================================================

CREATE TABLE region (
    id              UUID PRIMARY KEY,
    parent_id       UUID,
    name            VARCHAR(50) NOT NULL,
    level           SMALLINT NOT NULL CHECK (level IN (1, 2)),
    code            VARCHAR(20) NOT NULL,
    description     TEXT,
    cover_image_url VARCHAR(500),
    heat_score      NUMERIC(10, 2) NOT NULL DEFAULT 0,
    sort_weight     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_region_code ON region (code);
CREATE INDEX idx_region_parent_id ON region (parent_id);
CREATE INDEX idx_region_level ON region (level);

COMMENT ON TABLE region IS '省市行政区划';
COMMENT ON COLUMN region.level IS '层级：1=省，2=市';
COMMENT ON COLUMN region.code IS '行政区划编码';

CREATE TRIGGER trg_region_updated_at
    BEFORE UPDATE ON region
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE attraction_category (
    id              UUID PRIMARY KEY,
    name            VARCHAR(50) NOT NULL,
    category_type   VARCHAR(20) NOT NULL CHECK (category_type IN ('theme', 'level')),
    parent_id       UUID,
    description     VARCHAR(200),
    sort_weight     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_attr_cat_type_name ON attraction_category (category_type, name);
CREATE INDEX idx_attr_cat_type ON attraction_category (category_type, sort_weight);
CREATE INDEX idx_attr_cat_parent ON attraction_category (parent_id);

COMMENT ON TABLE attraction_category IS '景点分类字典（B端维护）';
COMMENT ON COLUMN attraction_category.category_type IS '分类类型：theme=主题类型（历史人文/自然景色），level=等级称号（5A景区/世界遗产）';
COMMENT ON COLUMN attraction_category.parent_id IS '上级分类，支持二级分类';

CREATE TRIGGER trg_attraction_category_updated_at
    BEFORE UPDATE ON attraction_category
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE attraction (
    id                      UUID PRIMARY KEY,
    name                    VARCHAR(100) NOT NULL,
    city_id                 UUID NOT NULL,
    latitude                NUMERIC(10, 7),
    longitude               NUMERIC(10, 7),
    address                 VARCHAR(255),
    summary                 VARCHAR(200),
    description             TEXT,
    image_urls              JSONB,
    ticket_price            NUMERIC(10, 2),
    opening_hours           JSONB,
    visit_duration_minutes  INTEGER,
    best_seasons            JSONB,
    website                 VARCHAR(500),
    phone                   VARCHAR(50),
    traffic_guide           TEXT,
    base_popularity         NUMERIC(10, 2) NOT NULL DEFAULT 50,
    is_published            BOOLEAN NOT NULL DEFAULT TRUE,
    sort_weight             INTEGER NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_attraction_name_city ON attraction (name, city_id);
CREATE INDEX idx_attraction_city_id ON attraction (city_id);
CREATE INDEX idx_attraction_published ON attraction (is_published, sort_weight DESC);
CREATE INDEX idx_attraction_geo ON attraction (latitude, longitude);

COMMENT ON TABLE attraction IS '景点信息';
COMMENT ON COLUMN attraction.base_popularity IS '基础热度权重（运营配置，0-100）';
COMMENT ON COLUMN attraction.opening_hours IS '开放时间，如 {"mon":"09:00-17:00"}';

CREATE TRIGGER trg_attraction_updated_at
    BEFORE UPDATE ON attraction
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE attraction_category_relation (
    id              UUID PRIMARY KEY,
    attraction_id   UUID NOT NULL,
    category_id     UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_attr_cat_rel ON attraction_category_relation (attraction_id, category_id);
CREATE INDEX idx_attr_cat_rel_attraction ON attraction_category_relation (attraction_id);
CREATE INDEX idx_attr_cat_rel_category ON attraction_category_relation (category_id);

COMMENT ON TABLE attraction_category_relation IS '景点与分类的关联（多对多）';


CREATE TABLE restaurant (
    id                  UUID PRIMARY KEY,
    name                VARCHAR(100) NOT NULL,
    city_id             UUID NOT NULL,
    cuisine_type        VARCHAR(50),
    latitude            NUMERIC(10, 7),
    longitude           NUMERIC(10, 7),
    address             VARCHAR(255),
    summary             TEXT,
    avg_cost            NUMERIC(10, 2),
    business_hours      JSONB,
    signature_dishes    JSONB,
    image_urls          JSONB,
    need_reservation    BOOLEAN NOT NULL DEFAULT FALSE,
    phone               VARCHAR(50),
    is_published        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_restaurant_city_id ON restaurant (city_id);
CREATE INDEX idx_restaurant_cuisine ON restaurant (cuisine_type);
CREATE INDEX idx_restaurant_geo ON restaurant (latitude, longitude);

COMMENT ON TABLE restaurant IS '餐厅信息';
COMMENT ON COLUMN restaurant.avg_cost IS '人均消费（元）';

CREATE TRIGGER trg_restaurant_updated_at
    BEFORE UPDATE ON restaurant
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE hotel (
    id              UUID PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    city_id         UUID NOT NULL,
    star_level      VARCHAR(20),
    latitude        NUMERIC(10, 7),
    longitude       NUMERIC(10, 7),
    address         VARCHAR(255),
    summary         TEXT,
    min_price       NUMERIC(10, 2),
    max_price       NUMERIC(10, 2),
    room_types      JSONB,
    facilities      JSONB,
    image_urls      JSONB,
    booking_url     VARCHAR(500),
    phone           VARCHAR(50),
    is_published    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_hotel_city_id ON hotel (city_id);
CREATE INDEX idx_hotel_star ON hotel (star_level);
CREATE INDEX idx_hotel_geo ON hotel (latitude, longitude);

COMMENT ON TABLE hotel IS '酒店信息';
COMMENT ON COLUMN hotel.star_level IS '星级：5星级/4星级/3星级/经济型/精品酒店/民宿';

CREATE TRIGGER trg_hotel_updated_at
    BEFORE UPDATE ON hotel
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE transport (
    id              UUID PRIMARY KEY,
    attraction_id   UUID NOT NULL,
    name            VARCHAR(100) NOT NULL,
    transport_type  VARCHAR(50),
    price           NUMERIC(10, 2),
    description     TEXT,
    operating_hours JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_transport_attraction_id ON transport (attraction_id);

COMMENT ON TABLE transport IS '景区专属交通（观光车、索道等），城际交通不入库';

CREATE TRIGGER trg_transport_updated_at
    BEFORE UPDATE ON transport
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE popularity_stat (
    id                  UUID PRIMARY KEY,
    attraction_id       UUID NOT NULL,
    view_count          BIGINT NOT NULL DEFAULT 0,
    click_count         BIGINT NOT NULL DEFAULT 0,
    plan_count          BIGINT NOT NULL DEFAULT 0,
    rating_sum          NUMERIC(12, 2) NOT NULL DEFAULT 0,
    rating_count        INTEGER NOT NULL DEFAULT 0,
    behavior_score      NUMERIC(10, 2) NOT NULL DEFAULT 0,
    final_popularity    NUMERIC(10, 2) NOT NULL DEFAULT 50,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_popularity_attraction ON popularity_stat (attraction_id);
CREATE INDEX idx_popularity_final ON popularity_stat (final_popularity DESC);

COMMENT ON TABLE popularity_stat IS '景点热度统计';
COMMENT ON COLUMN popularity_stat.behavior_score IS '用户行为得分（0-100）';
COMMENT ON COLUMN popularity_stat.final_popularity IS '最终热度 = base_popularity * 0.6 + behavior_score * 0.4';

CREATE TRIGGER trg_popularity_stat_updated_at
    BEFORE UPDATE ON popularity_stat
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


-- =============================================================
-- 3.3 知识库（M09）
-- =============================================================

CREATE TABLE knowledge_base (
    id                  UUID PRIMARY KEY,
    name                VARCHAR(100) NOT NULL,
    description         TEXT,
    icon                VARCHAR(50),
    capacity_gb         NUMERIC(10, 2) NOT NULL DEFAULT 5,
    used_bytes          BIGINT NOT NULL DEFAULT 0,
    chunk_size          INTEGER NOT NULL DEFAULT 1024,
    chunk_overlap       INTEGER NOT NULL DEFAULT 100,
    separator_config    JSONB NOT NULL,
    retrieval_top_k     INTEGER NOT NULL DEFAULT 5,
    retrieval_threshold NUMERIC(4, 3) NOT NULL DEFAULT 0.500,
    embedding_model_id  UUID NOT NULL,
    rerank_model_id     UUID,
    permission_scope    VARCHAR(20) NOT NULL DEFAULT 'all'
                        CHECK (permission_scope IN ('all', 'specific')),
    rebuild_status      VARCHAR(20) NOT NULL DEFAULT 'normal'
                        CHECK (rebuild_status IN ('normal', 'pending_rebuild', 'rebuilding')),
    doc_count           INTEGER NOT NULL DEFAULT 0,
    created_by          UUID NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_kb_embedding_model ON knowledge_base (embedding_model_id);
CREATE INDEX idx_kb_rerank_model ON knowledge_base (rerank_model_id);
CREATE INDEX idx_kb_rebuild_status ON knowledge_base (rebuild_status);

COMMENT ON TABLE knowledge_base IS 'RAG 知识库';
COMMENT ON COLUMN knowledge_base.separator_config IS '分隔符配置数组，含启用状态与优先级';
COMMENT ON COLUMN knowledge_base.retrieval_top_k IS '检索返回切片数，平台默认 5';
COMMENT ON COLUMN knowledge_base.retrieval_threshold IS '相似度阈值，平台默认 0.5';
COMMENT ON COLUMN knowledge_base.rebuild_status IS '非 normal 时该知识库暂停参与检索';
COMMENT ON COLUMN knowledge_base.doc_count IS '文档数（冗余字段，便于列表展示）';

CREATE TRIGGER trg_knowledge_base_updated_at
    BEFORE UPDATE ON knowledge_base
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE kb_document (
    id                  UUID PRIMARY KEY,
    knowledge_base_id   UUID NOT NULL,
    file_name           VARCHAR(255) NOT NULL,
    file_type           VARCHAR(20) NOT NULL,
    file_size_bytes     BIGINT NOT NULL,
    storage_key         VARCHAR(500) NOT NULL,
    source_url          VARCHAR(1000),
    process_status      VARCHAR(20) NOT NULL DEFAULT 'queued'
                        CHECK (process_status IN ('queued', 'parsing', 'chunking', 'embedding', 'success', 'failed')),
    process_progress    SMALLINT NOT NULL DEFAULT 0 CHECK (process_progress BETWEEN 0 AND 100),
    queue_position      INTEGER,
    error_message       TEXT,
    retry_count         INTEGER NOT NULL DEFAULT 0,
    markdown_content    TEXT,
    chunk_count         INTEGER,
    page_count          INTEGER,
    indexed_meta        JSONB,
    es_indexed          BOOLEAN NOT NULL DEFAULT FALSE,
    milvus_indexed      BOOLEAN NOT NULL DEFAULT FALSE,
    task_id             VARCHAR(100),
    uploaded_by         UUID NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_kbdoc_kb_id ON kb_document (knowledge_base_id, created_at DESC);
CREATE INDEX idx_kbdoc_status ON kb_document (process_status);
CREATE INDEX idx_kbdoc_task ON kb_document (task_id);

COMMENT ON TABLE kb_document IS '知识库文档';
COMMENT ON COLUMN kb_document.process_status IS '处理状态：queued=排队，parsing=解析中，chunking=切分中，embedding=向量化中，success=完成，failed=失败';
COMMENT ON COLUMN kb_document.indexed_meta IS '入库时的切分配置快照，用于识别旧参数文档';
COMMENT ON COLUMN kb_document.storage_key IS 'MinIO 中的对象键';

CREATE TRIGGER trg_kb_document_updated_at
    BEFORE UPDATE ON kb_document
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE kb_chunk (
    id                  UUID PRIMARY KEY,
    document_id         UUID NOT NULL,
    knowledge_base_id   UUID NOT NULL,
    chunk_index         INTEGER NOT NULL,
    heading_path        VARCHAR(500),
    content             TEXT NOT NULL,
    char_count          INTEGER NOT NULL,
    milvus_vector_id    VARCHAR(100),
    es_doc_id           VARCHAR(100),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_kbchunk_doc_index ON kb_chunk (document_id, chunk_index);
CREATE INDEX idx_kbchunk_kb_id ON kb_chunk (knowledge_base_id);
CREATE INDEX idx_kbchunk_milvus ON kb_chunk (milvus_vector_id);

COMMENT ON TABLE kb_chunk IS '文档切片（PG 为源数据，Milvus 存向量，ES 存索引副本）';
COMMENT ON COLUMN kb_chunk.heading_path IS '标题路径，如「第三章 > 3.2 太和殿」';


-- =============================================================
-- 3.4 知识图谱（M10）
-- 说明：实体详情存 PG，关系存 Neo4j，Neo4j 节点冗余 name 字段
-- =============================================================

CREATE TABLE kg_person (
    id                      UUID PRIMARY KEY,
    name                    VARCHAR(100) NOT NULL,
    alias                   VARCHAR(200),
    dynasty                 VARCHAR(50),
    occupation              VARCHAR(100),
    birth_year              INTEGER,
    death_year              INTEGER,
    hometown                VARCHAR(100),
    representative_works    JSONB,
    summary                 TEXT,
    image_url               VARCHAR(500),
    graph_sync_status       VARCHAR(20) NOT NULL DEFAULT 'synced'
                            CHECK (graph_sync_status IN ('pending', 'synced', 'failed')),
    graph_sync_error        TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_kgperson_name ON kg_person (name);
CREATE INDEX idx_kgperson_sync ON kg_person (graph_sync_status) WHERE graph_sync_status != 'synced';

COMMENT ON TABLE kg_person IS '知识图谱-历史人物';

CREATE TRIGGER trg_kg_person_updated_at
    BEFORE UPDATE ON kg_person
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE kg_event (
    id              UUID PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    event_time      VARCHAR(100),
    location        VARCHAR(200),
    event_type      VARCHAR(50),
    significance    TEXT,
    description     TEXT,
    graph_sync_status VARCHAR(20) NOT NULL DEFAULT 'synced'
                    CHECK (graph_sync_status IN ('pending', 'synced', 'failed')),
    graph_sync_error TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_kgevent_name ON kg_event (name);
CREATE INDEX idx_kgevent_sync ON kg_event (graph_sync_status) WHERE graph_sync_status != 'synced';

COMMENT ON TABLE kg_event IS '知识图谱-历史事件';
COMMENT ON COLUMN kg_event.event_time IS '发生时间，允许用朝代纪年表示（如「永乐十八年」），故用字符串';

CREATE TRIGGER trg_kg_event_updated_at
    BEFORE UPDATE ON kg_event
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE kg_culture (
    id              UUID PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    culture_type    VARCHAR(50)
                    CHECK (culture_type IN ('architecture', 'art', 'folklore', 'specialty')),
    region          VARCHAR(100),
    description     TEXT,
    image_url       VARCHAR(500),
    graph_sync_status VARCHAR(20) NOT NULL DEFAULT 'synced'
                    CHECK (graph_sync_status IN ('pending', 'synced', 'failed')),
    graph_sync_error TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_kgculture_type ON kg_culture (culture_type);
CREATE INDEX idx_kgculture_sync ON kg_culture (graph_sync_status) WHERE graph_sync_status != 'synced';

COMMENT ON TABLE kg_culture IS '知识图谱-文化元素';
COMMENT ON COLUMN kg_culture.culture_type IS '类型：architecture=建筑风格，art=艺术形式，folklore=民俗活动，specialty=地方特产';

CREATE TRIGGER trg_kg_culture_updated_at
    BEFORE UPDATE ON kg_culture
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE kg_relation_type (
    id              UUID PRIMARY KEY,
    code            VARCHAR(50) NOT NULL,
    name            VARCHAR(50) NOT NULL,
    cardinality     VARCHAR(20) NOT NULL CHECK (cardinality IN ('one_to_one', 'many_to_many')),
    source_types    JSONB NOT NULL,
    target_types    JSONB NOT NULL,
    is_builtin      BOOLEAN NOT NULL DEFAULT TRUE,
    description     VARCHAR(200),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_kgreltype_code ON kg_relation_type (code);

COMMENT ON TABLE kg_relation_type IS '知识图谱-关系类型元数据';
COMMENT ON COLUMN kg_relation_type.cardinality IS '基数：one_to_one=不允许重复，many_to_many=允许重复';
COMMENT ON COLUMN kg_relation_type.source_types IS '允许的起始实体类型数组，如 ["attraction"]';
COMMENT ON COLUMN kg_relation_type.target_types IS '允许的目标实体类型数组，如 ["person"]';


CREATE TABLE featured_knowledge_graph (
    id              UUID PRIMARY KEY,
    attraction_id   UUID NOT NULL,
    sort_weight     INTEGER NOT NULL DEFAULT 0,
    created_by      UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_fkg_attraction ON featured_knowledge_graph (attraction_id);
CREATE INDEX idx_fkg_sort ON featured_knowledge_graph (sort_weight DESC);

COMMENT ON TABLE featured_knowledge_graph IS '发现页精选知识图谱（B端运营配置，控制展示与排序）';
COMMENT ON COLUMN featured_knowledge_graph.attraction_id IS '被精选的景点，不可重复';
COMMENT ON COLUMN featured_knowledge_graph.sort_weight IS '展示排序权重，越大越靠前';


-- =============================================================
-- 3.5 对话与 Agent（M03、M06、M07）
-- =============================================================

CREATE TABLE chat_session (
    id                  UUID PRIMARY KEY,
    user_id             UUID NOT NULL,
    title               VARCHAR(200) NOT NULL DEFAULT '新对话',
    current_model_id    UUID,
    current_intent      VARCHAR(50),
    flow_state          VARCHAR(50),
    working_memory      JSONB,
    message_count       INTEGER NOT NULL DEFAULT 0,
    last_active_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chatsession_user ON chat_session (user_id, last_active_at DESC);
CREATE INDEX idx_chatsession_active ON chat_session (last_active_at DESC);

COMMENT ON TABLE chat_session IS '对话会话';
COMMENT ON COLUMN chat_session.current_model_id IS '会话级模型切换，新会话恢复平台默认';
COMMENT ON COLUMN chat_session.working_memory IS '工作记忆：候选景点、已生成方案、调整历史';

CREATE TRIGGER trg_chat_session_updated_at
    BEFORE UPDATE ON chat_session
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE chat_message (
    id              UUID PRIMARY KEY,
    session_id      UUID NOT NULL,
    role            VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content         TEXT NOT NULL,
    content_type    VARCHAR(20) NOT NULL DEFAULT 'text'
                    CHECK (content_type IN ('text', 'markdown', 'plan_card', 'clarify_options')),
    tool_calls      JSONB,
    citations       JSONB,
    model_id        UUID,
    token_input     INTEGER,
    token_output    INTEGER,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chatmsg_session ON chat_message (session_id, created_at ASC);
CREATE INDEX idx_chatmsg_created ON chat_message (created_at DESC);

COMMENT ON TABLE chat_message IS '对话消息';
COMMENT ON COLUMN chat_message.content_type IS '内容类型：plan_card=方案卡片，clarify_options=意图澄清选项';
COMMENT ON COLUMN chat_message.tool_calls IS '工具调用轨迹';
COMMENT ON COLUMN chat_message.citations IS '引用来源';


CREATE TABLE chat_pending_interaction (
    id                  UUID PRIMARY KEY,
    session_id          UUID NOT NULL,
    interaction_type    VARCHAR(50) NOT NULL
                        CHECK (interaction_type IN ('requirements', 'plan_selection', 'intent_clarify', 'adjustment_confirm')),
    payload             JSONB NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'answered', 'expired', 'cancelled')),
    answer              JSONB,
    expires_at          TIMESTAMPTZ,
    answered_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cpi_session ON chat_pending_interaction (session_id, status);
CREATE INDEX idx_cpi_pending ON chat_pending_interaction (status, created_at DESC) WHERE status = 'pending';
CREATE UNIQUE INDEX uk_cpi_session_pending ON chat_pending_interaction (session_id) WHERE status = 'pending';

COMMENT ON TABLE chat_pending_interaction IS '待处理的用户交互（SSE 中断时的选项，落库保证连接断开后可恢复）';
COMMENT ON COLUMN chat_pending_interaction.interaction_type IS '交互类型：requirements=需求收集，plan_selection=方案选择，intent_clarify=意图澄清，adjustment_confirm=调整确认';
COMMENT ON COLUMN chat_pending_interaction.payload IS '交互内容：选项列表、缺失字段说明、自定义输入提示等';
COMMENT ON COLUMN chat_pending_interaction.answer IS '用户的选择结果';
COMMENT ON COLUMN chat_pending_interaction.expires_at IS '过期时间，超时后标记为 expired';
-- 部分唯一索引 uk_cpi_session_pending 保证同一会话同时只允许一个待处理交互


CREATE TABLE agent_checkpoint (
    id                      UUID PRIMARY KEY,
    session_id              UUID NOT NULL,
    thread_id               VARCHAR(100) NOT NULL,
    checkpoint_id           VARCHAR(100) NOT NULL,
    parent_checkpoint_id    VARCHAR(100),
    state                   JSONB NOT NULL,
    metadata                JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agentcp_thread ON agent_checkpoint (thread_id, created_at DESC);
CREATE UNIQUE INDEX uk_agentcp_thread_checkpoint ON agent_checkpoint (thread_id, checkpoint_id);
CREATE INDEX idx_agentcp_session ON agent_checkpoint (session_id);

COMMENT ON TABLE agent_checkpoint IS 'LangGraph 检查点，用于中断恢复';
COMMENT ON COLUMN agent_checkpoint.state IS 'LangGraph 图状态快照';


CREATE TABLE memory_long_term (
    id                  UUID PRIMARY KEY,
    user_id             UUID NOT NULL,
    memory_type         VARCHAR(50) NOT NULL
                        CHECK (memory_type IN ('preference', 'behavior', 'context')),
    memory_key          VARCHAR(100) NOT NULL,
    memory_value        JSONB NOT NULL,
    confidence          NUMERIC(4, 3) NOT NULL DEFAULT 1.000,
    source              VARCHAR(50),
    last_active_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_memory_user_key ON memory_long_term (user_id, memory_type, memory_key);
CREATE INDEX idx_memory_user ON memory_long_term (user_id);
CREATE INDEX idx_memory_active ON memory_long_term (last_active_at DESC);

COMMENT ON TABLE memory_long_term IS '长期记忆（系统学习的用户偏好，区别于 user_profile 的显式设置）';
COMMENT ON COLUMN memory_long_term.confidence IS '置信度（0-1），与 last_active_at 共同参与衰减计算';
COMMENT ON COLUMN memory_long_term.source IS '来源：conversation/footprint/plan/rating';

CREATE TRIGGER trg_memory_long_term_updated_at
    BEFORE UPDATE ON memory_long_term
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


-- =============================================================
-- 3.6 旅游计划（M04）
-- =============================================================

CREATE TABLE trip_plan (
    id                      UUID PRIMARY KEY,
    user_id                 UUID NOT NULL,
    title                   VARCHAR(200) NOT NULL,
    destination_city_id     UUID,
    destination_text        VARCHAR(200) NOT NULL,
    start_date              DATE,
    end_date                DATE,
    day_count               INTEGER,
    budget_per_person       NUMERIC(12, 2),
    people_count            INTEGER NOT NULL DEFAULT 1,
    status                  VARCHAR(20) NOT NULL DEFAULT 'planning'
                            CHECK (status IN ('planning', 'pending', 'ongoing', 'completed', 'cancelled')),
    selected_candidate_id   UUID,
    edit_lock_user          UUID,
    edit_lock_at            TIMESTAMPTZ,
    confirmed_at            TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tripplan_user_status ON trip_plan (user_id, status, created_at DESC);
CREATE INDEX idx_tripplan_status_dates ON trip_plan (status, start_date, end_date);
CREATE INDEX idx_tripplan_destination ON trip_plan (destination_city_id);

COMMENT ON TABLE trip_plan IS '旅游计划';
COMMENT ON COLUMN trip_plan.destination_text IS '目的地文本，支持「北京+天津」这类多目的地';
COMMENT ON COLUMN trip_plan.status IS '状态：planning=规划中，pending=待进行，ongoing=进行中，completed=已完成，cancelled=已取消';
COMMENT ON COLUMN trip_plan.edit_lock_user IS '编辑锁持有者，同一行程同时只允许一个会话编辑';

CREATE TRIGGER trg_trip_plan_updated_at
    BEFORE UPDATE ON trip_plan
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE plan_candidate (
    id                  UUID PRIMARY KEY,
    plan_id             UUID NOT NULL,
    candidate_type      VARCHAR(20) NOT NULL
                        CHECK (candidate_type IN ('economy', 'standard', 'comfort', 'custom')),
    title               VARCHAR(200) NOT NULL,
    total_budget        NUMERIC(12, 2) NOT NULL,
    attraction_count    INTEGER NOT NULL DEFAULT 0,
    accommodation_level VARCHAR(50),
    transport_level     VARCHAR(50),
    dining_level        VARCHAR(50),
    recommend_score     NUMERIC(4, 2),
    is_selected         BOOLEAN NOT NULL DEFAULT FALSE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    content             JSONB NOT NULL,
    generated_by_session UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_plancand_plan ON plan_candidate (plan_id, is_active, created_at DESC);
CREATE INDEX idx_plancand_selected ON plan_candidate (plan_id, is_selected);

COMMENT ON TABLE plan_candidate IS '方案候选（未选中方案保留为备选）';
COMMENT ON COLUMN plan_candidate.candidate_type IS '方案类型：economy=经济型，standard=标准型，comfort=舒适型，custom=自定义';
COMMENT ON COLUMN plan_candidate.content IS '方案完整 JSON 快照，用于精确回放';
COMMENT ON COLUMN plan_candidate.is_active IS '是否为当前生效方案，false 表示备选';

CREATE TRIGGER trg_plan_candidate_updated_at
    BEFORE UPDATE ON plan_candidate
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE plan_day (
    id                  UUID PRIMARY KEY,
    plan_id             UUID NOT NULL,
    candidate_id        UUID NOT NULL,
    day_number          INTEGER NOT NULL,
    date                DATE,
    budget_breakdown    JSONB,
    summary             TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_planday_cand_day ON plan_day (candidate_id, day_number);
CREATE INDEX idx_planday_plan ON plan_day (plan_id);

COMMENT ON TABLE plan_day IS '计划日程（挂在方案下，因不同方案天数安排可能不同）';
COMMENT ON COLUMN plan_day.budget_breakdown IS '当日预算明细，如 {"ticket":420,"dining":850}';

CREATE TRIGGER trg_plan_day_updated_at
    BEFORE UPDATE ON plan_day
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE plan_activity (
    id              UUID PRIMARY KEY,
    plan_day_id     UUID NOT NULL,
    activity_type   VARCHAR(20) NOT NULL
                    CHECK (activity_type IN ('attraction', 'dining', 'transport', 'accommodation', 'rest')),
    start_time      TIME,
    end_time        TIME,
    title           VARCHAR(200) NOT NULL,
    description     TEXT,
    attraction_id   UUID,
    restaurant_id   UUID,
    hotel_id        UUID,
    cost            NUMERIC(10, 2),
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_planact_day ON plan_activity (plan_day_id, sort_order);
CREATE INDEX idx_planact_attraction ON plan_activity (attraction_id);

COMMENT ON TABLE plan_activity IS '行程活动';
COMMENT ON COLUMN plan_activity.activity_type IS '活动类型：attraction=景点，dining=餐饮，transport=交通，accommodation=住宿，rest=休息';

CREATE TRIGGER trg_plan_activity_updated_at
    BEFORE UPDATE ON plan_activity
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


-- =============================================================
-- 3.7 足迹（M05）
-- =============================================================

CREATE TABLE footprint (
    id              UUID PRIMARY KEY,
    user_id         UUID NOT NULL,
    attraction_id   UUID NOT NULL,
    visit_date      DATE NOT NULL,
    source          VARCHAR(20) NOT NULL CHECK (source IN ('auto_from_plan', 'manual')),
    trip_plan_id    UUID,
    rating          SMALLINT CHECK (rating BETWEEN 1 AND 5),
    review          TEXT,
    image_urls      JSONB,
    is_public       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_footprint_user ON footprint (user_id, visit_date DESC);
CREATE INDEX idx_footprint_attraction ON footprint (attraction_id);
CREATE INDEX idx_footprint_public ON footprint (is_public, created_at DESC);

COMMENT ON TABLE footprint IS '用户足迹';
COMMENT ON COLUMN footprint.source IS '来源：auto_from_plan=计划完成自动生成，manual=手动添加';
COMMENT ON COLUMN footprint.is_public IS '是否公开，供发现页精选游记使用';

CREATE TRIGGER trg_footprint_updated_at
    BEFORE UPDATE ON footprint
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


-- =============================================================
-- 3.8 模型与额度（M12、M13）
-- =============================================================

CREATE TABLE model (
    id                      UUID PRIMARY KEY,
    name                    VARCHAR(100) NOT NULL,
    category                VARCHAR(20) NOT NULL
                            CHECK (category IN ('chat', 'vision', 'embedding', 'rerank', 'ocr')),
    model_code              VARCHAR(100) NOT NULL,
    base_url                VARCHAR(500) NOT NULL,
    api_key_encrypted       TEXT,
    max_context_tokens      INTEGER,
    max_output_tokens       INTEGER,
    timeout_seconds         INTEGER NOT NULL DEFAULT 60,
    concurrency_limit       INTEGER,
    price_input             NUMERIC(12, 6),
    price_output            NUMERIC(12, 6),
    description             TEXT,
    is_enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    is_default              BOOLEAN NOT NULL DEFAULT FALSE,
    last_test_at            TIMESTAMPTZ,
    last_test_ok            BOOLEAN,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_model_category_code ON model (category, model_code, base_url);
CREATE INDEX idx_model_category ON model (category, is_enabled);
CREATE UNIQUE INDEX idx_model_default ON model (category) WHERE is_default = TRUE;

COMMENT ON TABLE model IS '模型注册（统一 OpenAI 兼容接口）';
COMMENT ON COLUMN model.category IS '类别：chat=文本对话，vision=图片理解，embedding=向量化，rerank=重排序，ocr=OCR解析';
COMMENT ON COLUMN model.model_code IS '调用模型 ID，如 deepseek-chat';
COMMENT ON COLUMN model.api_key_encrypted IS '加密后的 API Key，应用层解密使用';
COMMENT ON COLUMN model.is_default IS '每类别最多一个默认模型（部分唯一索引保证）';
COMMENT ON TABLE model IS '注意：无 vector_dim 字段，向量维度由配置文件控制';

CREATE TRIGGER trg_model_updated_at
    BEFORE UPDATE ON model
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


-- 按月分区表（日志类数据，可定期 DROP PARTITION 清理）
CREATE TABLE model_call_log (
    id              UUID NOT NULL,
    model_id        UUID NOT NULL,
    caller_type     VARCHAR(20) NOT NULL CHECK (caller_type IN ('user_chat', 'system_document')),
    user_id         UUID,
    session_id      UUID,
    document_id     UUID,
    token_input     INTEGER NOT NULL DEFAULT 0,
    token_output    INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER,
    is_success      BOOLEAN NOT NULL,
    error_type      VARCHAR(50),
    error_message   TEXT,
    cost_estimate   NUMERIC(12, 6),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE INDEX idx_mcalllog_model_time ON model_call_log (model_id, created_at DESC);
CREATE INDEX idx_mcalllog_user_time ON model_call_log (user_id, created_at DESC);
CREATE INDEX idx_mcalllog_caller ON model_call_log (caller_type, created_at DESC);
CREATE INDEX idx_mcalllog_success ON model_call_log (is_success, created_at DESC);

COMMENT ON TABLE model_call_log IS '模型调用日志（按月分区）';
COMMENT ON COLUMN model_call_log.caller_type IS '调用来源：user_chat=C端对话（计入额度），system_document=B端文档处理（不计入额度）';
COMMENT ON COLUMN model_call_log.error_type IS '失败类型：timeout/auth/rate_limit/server_error/format_invalid';

-- 初始分区（应用启动时或定时任务需持续创建未来分区）
CREATE TABLE model_call_log_p2026_11 PARTITION OF model_call_log
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE model_call_log_p2026_12 PARTITION OF model_call_log
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');
CREATE TABLE model_call_log_default PARTITION OF model_call_log DEFAULT;


CREATE TABLE user_quota (
    id              UUID PRIMARY KEY,
    user_id         UUID NOT NULL,
    quota_date      DATE NOT NULL,
    call_count      INTEGER NOT NULL DEFAULT 0,
    token_used      BIGINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_quota_user_date ON user_quota (user_id, quota_date);
CREATE INDEX idx_quota_date ON user_quota (quota_date);

COMMENT ON TABLE user_quota IS '用户额度（按用户×日期一行，自然日重置）';
COMMENT ON COLUMN user_quota.call_count IS '当日已调用次数（Redis 实时计数，异步同步到此）';
COMMENT ON COLUMN user_quota.token_used IS '当日已用 token';

CREATE TRIGGER trg_user_quota_updated_at
    BEFORE UPDATE ON user_quota
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


-- =============================================================
-- 3.9 平台运营（M14、M15、M17）
-- =============================================================

CREATE TABLE admin_user (
    id              UUID PRIMARY KEY,
    username        VARCHAR(50) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    real_name       VARCHAR(50),
    email           VARCHAR(100),
    status          VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    token_version   INTEGER NOT NULL DEFAULT 0,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_admin_username ON admin_user (username);

COMMENT ON TABLE admin_user IS 'B端管理员账号';
COMMENT ON COLUMN admin_user.token_version IS 'Token 版本号，登出/改密/禁用时自增，使所有已签发 Token 失效';

CREATE TRIGGER trg_admin_user_updated_at
    BEFORE UPDATE ON admin_user
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE role (
    id              UUID PRIMARY KEY,
    code            VARCHAR(50) NOT NULL,
    name            VARCHAR(50) NOT NULL,
    description     VARCHAR(200),
    is_builtin      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_role_code ON role (code);

COMMENT ON TABLE role IS '角色（当前内置超级管理员与普通用户，结构支持扩展）';

CREATE TRIGGER trg_role_updated_at
    BEFORE UPDATE ON role
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE permission (
    id              UUID PRIMARY KEY,
    code            VARCHAR(100) NOT NULL,
    module          VARCHAR(50) NOT NULL,
    action          VARCHAR(20) NOT NULL
                    CHECK (action IN ('create', 'read', 'update', 'delete', 'export', 'manage')),
    name            VARCHAR(100) NOT NULL,
    description     VARCHAR(200),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_permission_code ON permission (code);
CREATE INDEX idx_permission_module ON permission (module, action);

COMMENT ON TABLE permission IS '权限项（模块 × 操作，细粒度）';
COMMENT ON COLUMN permission.code IS '权限编码，如 catalog.attraction.delete';


CREATE TABLE role_permission (
    id              UUID PRIMARY KEY,
    role_id         UUID NOT NULL,
    permission_id   UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_role_perm ON role_permission (role_id, permission_id);
CREATE INDEX idx_roleperm_role ON role_permission (role_id);

COMMENT ON TABLE role_permission IS '角色权限关联';


CREATE TABLE admin_user_role (
    id              UUID PRIMARY KEY,
    admin_user_id   UUID NOT NULL,
    role_id         UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_admin_role ON admin_user_role (admin_user_id, role_id);
CREATE INDEX idx_adminrole_admin ON admin_user_role (admin_user_id);

COMMENT ON TABLE admin_user_role IS '管理员角色关联';


CREATE TABLE operation_log (
    id              UUID PRIMARY KEY,
    admin_user_id   UUID NOT NULL,
    module          VARCHAR(50) NOT NULL,
    action          VARCHAR(20) NOT NULL
                    CHECK (action IN ('create', 'update', 'delete', 'export', 'login', 'logout')),
    target_type     VARCHAR(50),
    target_id       UUID,
    detail          JSONB,
    ip_address      VARCHAR(45),
    user_agent      VARCHAR(500),
    is_success      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_oplog_admin ON operation_log (admin_user_id, created_at DESC);
CREATE INDEX idx_oplog_module ON operation_log (module, created_at DESC);
CREATE INDEX idx_oplog_time ON operation_log (created_at DESC);

COMMENT ON TABLE operation_log IS '操作日志（仅记录增删改与登录登出，不记录查询）';


-- 按月分区表（日志类数据，可定期 DROP PARTITION 清理）
CREATE TABLE user_event (
    id              UUID NOT NULL,
    user_id         UUID,
    event_type      VARCHAR(50) NOT NULL,
    target_type     VARCHAR(50),
    target_id       UUID,
    session_id      UUID,
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE INDEX idx_uevent_user_time ON user_event (user_id, created_at DESC);
CREATE INDEX idx_uevent_type_time ON user_event (event_type, created_at DESC);
CREATE INDEX idx_uevent_target ON user_event (target_type, target_id);

COMMENT ON TABLE user_event IS '用户行为埋点（按月分区）';
COMMENT ON COLUMN user_event.event_type IS '事件类型：view/click/share/create_plan/complete_plan/chat_send/graph_view';

-- 初始分区（应用启动时或定时任务需持续创建未来分区）
CREATE TABLE user_event_p2026_11 PARTITION OF user_event
    FOR VALUES FROM ('2026-11-01') TO ('2026-12-01');
CREATE TABLE user_event_p2026_12 PARTITION OF user_event
    FOR VALUES FROM ('2026-12-01') TO ('2027-01-01');
CREATE TABLE user_event_default PARTITION OF user_event DEFAULT;


CREATE TABLE activity (
    id              UUID PRIMARY KEY,
    title           VARCHAR(200) NOT NULL,
    description     TEXT,
    cover_image_url VARCHAR(500),
    activity_type   VARCHAR(50)
                    CHECK (activity_type IN ('discount', 'festival', 'exhibition', 'other')),
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    city_id         UUID,
    attraction_id   UUID,
    detail_url      VARCHAR(500),
    is_published    BOOLEAN NOT NULL DEFAULT TRUE,
    sort_weight     INTEGER NOT NULL DEFAULT 0,
    created_by      UUID NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_activity_date CHECK (end_date >= start_date)
);

CREATE INDEX idx_activity_published ON activity (is_published, sort_weight DESC);
CREATE INDEX idx_activity_dates ON activity (start_date, end_date) WHERE is_published = TRUE;
CREATE INDEX idx_activity_city ON activity (city_id) WHERE city_id IS NOT NULL;
CREATE INDEX idx_activity_attraction ON activity (attraction_id) WHERE attraction_id IS NOT NULL;

COMMENT ON TABLE activity IS '旅游活动（发现页推荐用）';
COMMENT ON COLUMN activity.activity_type IS '类型：discount=特惠，festival=节庆，exhibition=展览，other=其他';
COMMENT ON COLUMN activity.city_id IS '目标城市，NULL 表示全国性活动';
COMMENT ON COLUMN activity.attraction_id IS '关联景点，NULL 表示不限定';
COMMENT ON COLUMN activity.detail_url IS '活动详情页外部链接，价格等信息在此页面展示';
COMMENT ON COLUMN activity.id IS '活动状态（未开始/进行中/已结束）由 start_date、end_date 与当前时间实时计算，不单独存储';

CREATE TRIGGER trg_activity_updated_at
    BEFORE UPDATE ON activity
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


CREATE TABLE notification (
    id                  UUID PRIMARY KEY,
    user_id             UUID NOT NULL,
    notification_type   VARCHAR(50) NOT NULL
                        CHECK (notification_type IN ('plan_starting', 'plan_ended', 'system')),
    title               VARCHAR(200) NOT NULL,
    content             TEXT,
    related_type        VARCHAR(50),
    related_id          UUID,
    is_read             BOOLEAN NOT NULL DEFAULT FALSE,
    read_at             TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notification_user ON notification (user_id, created_at DESC);
CREATE INDEX idx_notification_unread ON notification (user_id, is_read) WHERE is_read = FALSE;
CREATE INDEX idx_notification_type ON notification (notification_type, created_at DESC);

COMMENT ON TABLE notification IS '站内通知';
COMMENT ON COLUMN notification.notification_type IS '通知类型：plan_starting=计划即将开始，plan_ended=计划已结束（提醒确认完成），system=系统通知';
COMMENT ON COLUMN notification.related_type IS '关联对象类型：plan / footprint / system';
COMMENT ON COLUMN notification.related_id IS '关联对象 ID，点击通知可跳转到对应页面';


CREATE TABLE site_setting (
    id              UUID PRIMARY KEY,
    setting_key     VARCHAR(100) NOT NULL,
    setting_value   JSONB NOT NULL,
    description     VARCHAR(200),
    updated_by      UUID,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uk_setting_key ON site_setting (setting_key);

COMMENT ON TABLE site_setting IS '平台级配置（键值对）';

CREATE TRIGGER trg_site_setting_updated_at
    BEFORE UPDATE ON site_setting
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();


-- =============================================================
-- 建表完成
-- =============================================================
-- 主表数量：43（另有 6 个分区子表）
-- 索引数量：103
--
-- 说明：
-- 1. 所有主键使用 UUID，应用层生成 UUIDv7
-- 2. 无物理外键，关联关系由应用层维护
-- 3. 所有时间字段使用 TIMESTAMPTZ（UTC）
-- 4. updated_at 由触发器自动维护
-- 5. 部分唯一索引 idx_model_default 保证每类别最多一个默认模型
-- 6. model_call_log 与 user_event 按月 RANGE 分区，需定时任务创建未来分区
-- =============================================================
