# Hair Salon AI Agent

美发门店智能运营系统，覆盖 AI 对话预约、发型师空档、员工日程、会员积分、生日营销和护理知识问答。

## 项目亮点

- 对话式业务入口：用户可以直接说“推荐护理发型师”“我叫李雷，预约护理，slot_id: xxx”“取消预约 xxx”。
- 真实业务闭环：聊天入口会调用发型师、时间槽、预约、会员、营销等后端服务，不是固定文案。
- 可演示前端：后端启动后访问 `/` 即可打开运营台。
- 双层 Agent：客户侧保留稳定规则型 ChatAgent；员工侧使用 LangGraph 编排只读查询、RAG 检索和人工确认流程。
- 可测试：核心预约、权限、钱包、通知、LangGraph 工具、人工确认事务和留存分层都有 pytest 覆盖。

## 技术栈

- Backend：FastAPI、Pydantic、SQLAlchemy
- Database：SQLite 默认运行，`DATABASE_URL` 可切 PostgreSQL
- Agent：规则型 ChatAgent + LangChain 工具适配 + LangGraph 工作流
- RAG：内置美发知识库，BM25 离线检索兜底，可选 ChromaDB 向量检索
- Frontend：静态 HTML/CSS/JavaScript
- Test：pytest、FastAPI TestClient

## 快速启动

```powershell
pip install -r requirements.txt
python -m backend.database.init_db
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

如需接入真实模型，复制 `配置模板-会上传-只填占位符.env.example` 为 `.env`，再填写本地配置：

```powershell
Copy-Item "配置模板-会上传-只填占位符.env.example" .env
```

DeepSeek 示例：

```env
LLM_API_KEY=your-deepseek-key
LLM_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
RAG_USE_CHROMA=false
```

Ollama 示例：

```env
LLM_API_KEY=ollama
LLM_API_BASE=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434
RAG_USE_CHROMA=false
```

默认 `RAG_USE_CHROMA=false`，系统使用内置护理知识库，保证离线可演示。如果要启用 ChromaDB 向量检索，可以改为：

```env
RAG_USE_CHROMA=true
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
```

敏感演示接口可以配置管理员 Token：

```env
ADMIN_TOKEN=your-local-admin-token
```

设置后，`POST /api/init-db` 必须带请求头 `X-Admin-Token`。本地面试演示如果不需要这个保护，可以保持为空。

启动后打开：

```text
http://localhost:8000/
```

员工工作台：

```text
http://localhost:8000/staff
```

员工账号由 `.env` 中的 `DEMO_STAFF_PASSWORD` 和初始化脚本创建的示例发型师账号提供；管理员账号使用 `DEMO_ADMIN_PHONE` 和 `DEMO_ADMIN_PASSWORD`。员工端不开放公开注册。

API 文档：

```text
http://localhost:8000/docs
```

## 已完成功能

- `POST /api/chat`：聊天推荐、护理问答、预约、取消预约、查询预约
- `POST /api/chat/langchain`：LangChain 适配入口，未配置大模型时走稳定规则 Agent
- `POST /api/staff/agent/query`：LangGraph 员工只读查询，返回工具动作和数据来源
- `POST /api/staff/agent/appointment-change/propose`：生成预约调整方案，不写数据库
- `POST /api/staff/agent/tasks/{task_id}/confirm`：员工确认或拒绝预约调整方案
- `POST /api/retention/agent/run`：LangGraph 客户留存分层和运营建议
- `GET /api/notifications`：客户读取自己的站内通知
- `GET /api/stylists`：发型师查询
- `GET /api/stylists/{stylist_id}/slots`：可用时间槽
- `POST /api/appointments`：创建预约
- `GET /api/appointments`：按手机号查询预约
- `DELETE /api/appointments/{appointment_id}`：取消预约
- `GET /api/staff/schedule`：员工日程
- `POST /api/members`：创建会员
- `POST /api/transactions`：记录消费并加积分
- `GET /api/marketing/birthdays`：生日营销名单

## 测试

```powershell
pytest -q
```

当前全量测试为 42 条，覆盖登录权限、预约归属、钱包退款、通知已读、迁移、员工只读 Graph、RAG 来源、预约人工确认、留存分层、客户通知、员工页面和初始化幂等性。

## 交付检查

```powershell
python -m backend.database.init_db
pytest -q
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

验收顺序：

1. 打开 `http://localhost:8000/api/health`，确认 API 正常。
2. 打开 `http://localhost:8000/`，确认前端运营台能加载发型师、日程和会员数据。
3. 在 AI 对话里完成一次推荐、预约、查询和取消。
4. 在会员营销页创建会员、记录消费，确认积分增加。
5. 将会员生日设置为当天 `MM-DD`，点击生日营销，确认名单返回。
6. 使用员工账号打开 `/staff`，查询“今天有哪些预约”，确认回答带有数据库来源。
7. 在员工端运行运营分析，查看流失风险、余额客户和会员到期建议。
8. 在预约调整区生成方案，先确认数据库不变，再点击确认，验证客户通知和审计记录。

## 演示流程

1. 打开 `http://localhost:8000/`。
2. 在 AI 对话中发送：`推荐一个擅长护理的发型师`。
3. 从回复中复制一个 `slot_id`。
4. 发送：`我叫李雷，预约护理，slot_id: <slot_id>`。
5. 在客户预约区域按手机号查询预约。
6. 发送：`取消预约 <appointment_id>`，确认状态变为 `cancelled`。
7. 进入会员营销页，创建会员、记录消费、查看积分变化。
8. 将会员生日设置为今天的 `MM-DD`，点击生日营销查看营销名单。

## 3 分钟面试演示脚本

第一步讲项目目标：这是一个美发门店智能运营系统，不只做聊天，而是把聊天入口和真实业务闭环接起来。用户可以通过自然语言推荐发型师、查询空档、创建预约、取消预约，同时门店侧能查看员工日程、会员积分和生日营销名单。

第二步讲技术分层：FastAPI 负责 HTTP 接口，Pydantic 做请求和响应校验，SQLAlchemy 负责数据库模型和业务查询。Agent 层不直接写数据库，而是编排已有服务，比如先识别用户要护理，再查询擅长护理的发型师和可用时间槽，最后调用预约服务创建订单。

第三步讲 Agent 分层：客户侧用规则型 ChatAgent 保证预约闭环稳定；员工侧用 LangGraph 把意图识别、数据库查询、RAG 检索和结果整理拆成节点。LangChain 负责模型和工具适配，LangGraph 负责流程编排；大模型不能直接写数据库。

第四步现场演示：先在客户端完成登录、预约和通知查看；再切到 `/staff`，查询当天预约和客户会员。接着运行留存分析，展示可解释的分层建议；最后生成预约调整方案，强调方案阶段不写库，员工确认后才执行事务，并让客户刷新看到站内通知。

第五步讲测试保障：pytest 覆盖推荐返回 slot、本人预约取消、禁止取消别人预约、退款事务、通知已读、LangGraph 查询来源、RAG 召回、人工确认前后数据差异和留存分层。这样可以证明核心流程不是写死文案，而是真正调用后端服务。

## 主要接口

- `POST /api/chat`：稳定聊天入口。
- `POST /api/chat/langchain`：LangChain 适配入口，未配置 Key 时回退到规则 Agent。
- `POST /api/staff/agent/query`：员工只读 LangGraph 查询。
- `POST /api/staff/agent/appointment-change/propose`：预约调整提议。
- `GET /api/staff/agent/tasks/{task_id}`：查看本人发起的 Agent 任务。
- `POST /api/staff/agent/tasks/{task_id}/confirm`：确认或拒绝预约调整。
- `POST /api/retention/agent/run`：运行留存运营 Graph。
- `GET /api/stylists`：查询发型师。
- `GET /api/stylists/{stylist_id}/slots`：查询发型师空档。
- `POST /api/appointments`：创建预约。
- `GET /api/appointments?phone=...`：按手机号查询预约。
- `DELETE /api/appointments/{appointment_id}`：取消预约。
- `GET /api/staff/schedule`：查看员工日程。
- `POST /api/members`：创建或更新会员。
- `GET /api/members`：会员列表。
- `POST /api/transactions`：记录消费并增加积分。
- `GET /api/marketing/birthdays`：生日营销名单。

## 面试讲法

这个项目先用规则型 ChatAgent 把客户业务闭环跑通，再用 LangChain 接入工具调用，最后用 LangGraph 组织员工侧的多步骤工作流。这样做的原因是先验证底层业务服务，再增加模型能力；模型只负责理解问题和选择受控工具，业务服务本身不直接暴露给模型。

整体分层是：API 路由负责 HTTP 输入输出，Agent 层负责任务编排，Service 层负责数据库业务，前端负责演示流程。这种结构便于调试、演示和逐步升级。

员工只读 Graph 会返回 `actions` 和 `sources`。例如预约查询来源是 SQLAlchemy 数据库工具，护理问题来源是 RAG 检索结果。回答失败时只影响 Agent 请求，不会影响普通预约接口。

预约调整采用两阶段状态机：提议节点读取预约和新时间槽，人工确认节点暂停流程；只有确认接口收到 `confirmed=true` 后，事务节点才修改预约、释放旧时间槽、占用新时间槽、写审计并发送客户通知。

RAG 也采用可回退设计：默认走内置护理知识库，先尝试 Chroma 向量检索，未配置 embedding 或向量库不可用时回退到本地 BM25。面试时可以强调这是为了把“业务稳定性”和“AI 增强能力”解耦。实时预约和余额不放进 RAG，而是直接查询数据库。

权限设计上，客户和员工都通过 JWT 识别身份；员工 Agent、退款审核、留存工作台和预约确认都使用 `require_staff`。关键写操作还会写审计。当前版本没有引入 MCP，因为内部工具由 LangGraph 直接调用已经足够；如果未来需要把同一批工具提供给多个 Agent 或外部系统，再增加 MCP Server/Client 边界更合理。

前端当前使用静态 HTML/CSS/JavaScript，是为了降低部署和演示成本，把面试重点放在后端业务闭环、Agent 编排和可测试性上。后续如果产品化，可以迁移到 Vue 或 React，但 API 合同和后端服务边界不需要重写。
