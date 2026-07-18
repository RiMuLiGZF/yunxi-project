"""
[GAP-004] A2A 协议完整性测试

测试 A2A 协议的完整功能：
- Task 状态机
- AgentCard 签名验证
- MemoryTransport
- HttpTransport
- A2AProtocolServer
- 握手协议
- 协议版本协商
- 流式更新
- 标准化错误码
"""
import sys
import pytest
import asyncio

from agent_cluster.core.a2a_protocol import (
    Task,
    TaskStatus,
    TaskUpdate,
    Artifact,
    AgentCard,
    MemoryTransport,
    HttpTransport,
    A2AClient,
    A2AProtocolServer,
    sign_task,
    verify_task,
    A2A_PROTOCOL_VERSION,
    A2A_PROTOCOL_VERSIONS_SUPPORTED,
    A2A_ERROR_CODES,
    create_a2a_server,
    _negotiate_version,
    _build_a2a_error,
)


# ============================================================================
# Task 状态机测试
# ============================================================================

class TestTaskStateMachine:
    """Task 状态机测试"""

    def test_task_default_status(self):
        """默认状态为 SUBMITTED"""
        task = Task()
        assert task.status == TaskStatus.SUBMITTED

    def test_valid_transition_submitted_to_working(self):
        """SUBMITTED -> WORKING 合法"""
        task = Task()
        task.transition_to(TaskStatus.WORKING)
        assert task.status == TaskStatus.WORKING

    def test_valid_transition_working_to_completed(self):
        """WORKING -> COMPLETED 合法"""
        task = Task(status=TaskStatus.WORKING)
        task.transition_to(TaskStatus.COMPLETED)
        assert task.status == TaskStatus.COMPLETED

    def test_valid_transition_working_to_failed(self):
        """WORKING -> FAILED 合法"""
        task = Task(status=TaskStatus.WORKING)
        task.transition_to(TaskStatus.FAILED)
        assert task.status == TaskStatus.FAILED

    def test_valid_transition_working_to_input_required(self):
        """WORKING -> INPUT_REQUIRED 合法"""
        task = Task(status=TaskStatus.WORKING)
        task.transition_to(TaskStatus.INPUT_REQUIRED)
        assert task.status == TaskStatus.INPUT_REQUIRED

    def test_valid_transition_input_required_to_working(self):
        """INPUT_REQUIRED -> WORKING 合法"""
        task = Task(status=TaskStatus.INPUT_REQUIRED)
        task.transition_to(TaskStatus.WORKING)
        assert task.status == TaskStatus.WORKING

    def test_valid_transition_submitted_to_cancelled(self):
        """SUBMITTED -> CANCELLED 合法"""
        task = Task()
        task.transition_to(TaskStatus.CANCELLED)
        assert task.status == TaskStatus.CANCELLED

    def test_invalid_transition_completed_to_working(self):
        """COMPLETED -> WORKING 非法"""
        task = Task(status=TaskStatus.COMPLETED)
        with pytest.raises(ValueError):
            task.transition_to(TaskStatus.WORKING)

    def test_invalid_transition_failed_to_completed(self):
        """FAILED -> COMPLETED 非法"""
        task = Task(status=TaskStatus.FAILED)
        with pytest.raises(ValueError):
            task.transition_to(TaskStatus.COMPLETED)

    def test_task_to_dict(self):
        """Task 序列化"""
        task = Task(
            task_id="test-123",
            status=TaskStatus.WORKING,
            sender="agent.a",
            recipient="agent.b",
            description="test task",
            payload={"key": "value"},
            trace_id="trace-001",
        )
        d = task.to_dict()
        assert d["task_id"] == "test-123"
        assert d["status"] == "working"
        assert d["sender"] == "agent.a"
        assert d["recipient"] == "agent.b"
        assert d["payload"] == {"key": "value"}
        assert d["trace_id"] == "trace-001"

    def test_task_auto_generates_id(self):
        """Task 自动生成 ID"""
        task = Task()
        assert task.task_id != ""
        assert len(task.task_id) > 0

    def test_artifact_creation(self):
        """Artifact 创建"""
        art = Artifact(
            name="result.txt",
            kind="text",
            data="hello world",
        )
        assert art.artifact_id != ""
        assert art.name == "result.txt"
        assert art.kind == "text"
        assert art.data == "hello world"


# ============================================================================
# AgentCard 签名测试
# ============================================================================

class TestAgentCardSigning:
    """AgentCard 签名验证测试"""

    def test_sign_and_verify(self):
        """签名后能正确验证"""
        card = AgentCard(
            agent_id="agent.test",
            name="Test Agent",
            version="1.0.0",
            capabilities=["test.action"],
        )
        secret = "test-secret-123"
        card.sign(secret)
        assert card.signature != ""
        assert card.verify(secret) is True

    def test_verify_with_wrong_secret(self):
        """错误密钥验证失败"""
        card = AgentCard(
            agent_id="agent.test",
            capabilities=["test"],
        )
        card.sign("correct-secret")
        assert card.verify("wrong-secret") is False

    def test_tampered_card_fails_verify(self):
        """篡改内容后验证失败"""
        card = AgentCard(
            agent_id="agent.test",
            capabilities=["original"],
        )
        secret = "test-secret"
        card.sign(secret)

        # 篡改能力列表
        card.capabilities = ["tampered"]
        assert card.verify(secret) is False

    def test_agent_card_to_dict(self):
        """AgentCard 序列化"""
        card = AgentCard(
            agent_id="agent.test",
            name="Test",
            description="A test agent",
            version="1.2.3",
            url="https://example.com/a2a",
            capabilities=["action1", "action2"],
        )
        d = card.to_dict()
        assert d["agent_id"] == "agent.test"
        assert d["name"] == "Test"
        assert d["version"] == "1.2.3"
        assert d["url"] == "https://example.com/a2a"
        assert len(d["capabilities"]) == 2


# ============================================================================
# Task 签名测试
# ============================================================================

class TestTaskSigning:
    """Task 签名验证测试"""

    def test_sign_and_verify_task(self):
        """Task 签名和验证"""
        task = Task(
            task_id="task-1",
            sender="agent.a",
            recipient="agent.b",
            payload={"data": "test"},
        )
        secret = "my-secret"
        signature = sign_task(task, secret)
        assert signature != ""
        assert verify_task(task, signature, secret) is True

    def test_verify_task_wrong_secret(self):
        """错误密钥验证失败"""
        task = Task(task_id="task-1", payload={"data": "test"})
        signature = sign_task(task, "correct")
        assert verify_task(task, signature, "wrong") is False

    def test_tampered_task_fails_verify(self):
        """篡改 payload 后验证失败"""
        task = Task(task_id="task-1", payload={"data": "original"})
        secret = "my-secret"
        signature = sign_task(task, secret)

        task.payload = {"data": "tampered"}
        assert verify_task(task, signature, secret) is False


# ============================================================================
# MemoryTransport 测试
# ============================================================================

class TestMemoryTransport:
    """内存传输测试"""

    @pytest.fixture
    def transport(self):
        return MemoryTransport()

    @pytest.mark.asyncio
    async def test_send_to_registered_handler(self, transport):
        """发送到已注册的 handler"""
        async def handler(task):
            return TaskUpdate(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                is_final=True,
            )

        transport.register_handler("agent.test", handler)
        task = Task(sender="caller", recipient="agent.test")
        update = await transport.send("memory://agent.test", task)
        assert update.status == TaskStatus.COMPLETED
        assert update.is_final is True

    @pytest.mark.asyncio
    async def test_send_to_unregistered_agent(self, transport):
        """发送到未注册的 Agent 返回失败"""
        task = Task()
        update = await transport.send("memory://unknown", task)
        assert update.status == TaskStatus.FAILED
        assert update.error is not None
        assert "not found" in update.error.lower()

    @pytest.mark.asyncio
    async def test_handler_exception_returns_failed(self, transport):
        """handler 抛出异常返回失败"""
        async def bad_handler(task):
            raise RuntimeError("something went wrong")

        transport.register_handler("agent.bad", bad_handler)
        task = Task()
        update = await transport.send("memory://agent.bad", task)
        assert update.status == TaskStatus.FAILED
        assert "something went wrong" in update.error

    def test_get_handlers(self, transport):
        """获取所有已注册 handler"""
        transport.register_handler("a", lambda x: None)
        transport.register_handler("b", lambda x: None)
        handlers = transport.get_handlers()
        assert "a" in handlers
        assert "b" in handlers
        assert len(handlers) == 2


# ============================================================================
# A2AClient 测试
# ============================================================================

class TestA2AClient:
    """A2A 客户端测试"""

    @pytest.mark.asyncio
    async def test_send_task_via_memory(self):
        """通过内存传输发送 Task"""
        transport = MemoryTransport()

        async def handler(task):
            return TaskUpdate(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                artifact=Artifact(name="result", data="done"),
                is_final=True,
            )

        transport.register_handler("agent.test", handler)

        client = A2AClient(transport=transport)
        card = AgentCard(agent_id="agent.test", name="Test")
        task = Task(sender="client", description="test task")

        result = await client.send_task(card, task)
        assert result.status == TaskStatus.COMPLETED
        assert len(result.artifacts) == 1
        assert result.artifacts[0].name == "result"

    @pytest.mark.asyncio
    async def test_send_task_updates_recipient(self):
        """发送 Task 时设置 recipient"""
        transport = MemoryTransport()

        async def handler(task):
            return TaskUpdate(task_id=task.task_id, status=TaskStatus.WORKING)

        transport.register_handler("agent.target", handler)

        client = A2AClient(transport=transport)
        card = AgentCard(agent_id="agent.target")
        task = Task(sender="client")

        result = await client.send_task(card, task)
        assert result.recipient == "agent.target"

    @pytest.mark.asyncio
    async def test_handshake_memory_transport(self):
        """内存传输握手"""
        client = A2AClient()
        result = await client.handshake("memory://agent.test")
        assert result["success"] is True
        assert result["protocol_version"] == A2A_PROTOCOL_VERSION
        assert result["agent_id"] == "agent.test"

    def test_verify_card(self):
        """验证 AgentCard 签名"""
        secret = "test-secret"
        client = A2AClient(signing_secret=secret)

        card = AgentCard(agent_id="agent.test", capabilities=["test"])
        card.sign(secret)

        assert client.verify_card(card) is True


# ============================================================================
# A2AProtocolServer 测试
# ============================================================================

class TestA2AProtocolServer:
    """A2A 协议服务端测试"""

    @pytest.fixture
    def server(self):
        card = AgentCard(
            agent_id="agent.server",
            name="Server Agent",
            version="2.0.0",
            capabilities=["chat", "code", "search"],
        )
        return A2AProtocolServer(agent_card=card)

    def test_get_agent_card(self, server):
        """获取 AgentCard"""
        card = server.get_agent_card()
        assert card["agent_id"] == "agent.server"
        assert card["protocol_version"] == A2A_PROTOCOL_VERSION
        assert "supported_versions" in card
        assert A2A_PROTOCOL_VERSION in card["supported_versions"]

    def test_handshake_success(self, server):
        """握手成功"""
        result = server.handle_handshake({
            "client_id": "client-1",
            "supported_versions": ["1.0", "0.9"],
        })
        assert result["success"] is True
        assert result["protocol_version"] == "1.0"
        assert result["server_id"] == "agent.server"
        assert "endpoints" in result
        assert "submit" in result["endpoints"]

    def test_handshake_version_mismatch(self, server):
        """版本不兼容握手失败"""
        result = server.handle_handshake({
            "client_id": "old-client",
            "supported_versions": ["0.1", "0.2"],
        })
        assert result["success"] is False
        assert "error_code" in result
        assert result["error_code"] == A2A_ERROR_CODES["PROTOCOL_VERSION_MISMATCH"][0]

    def test_handshake_single_version_string(self, server):
        """单版本字符串也能工作"""
        result = server.handle_handshake({
            "client_id": "client-2",
            "protocol_version": "1.0",
        })
        assert result["success"] is True
        assert result["protocol_version"] == "1.0"

    @pytest.mark.asyncio
    async def test_submit_task_without_handler(self, server):
        """无 handler 时提交 Task"""
        result = await server.submit_task({
            "sender": "client",
            "description": "test task",
            "payload": {"data": "hello"},
        })
        assert "task_id" in result
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_submit_task_with_handler(self, server):
        """有 handler 时提交 Task"""
        async def handler(task):
            return TaskUpdate(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                artifact=Artifact(name="output", data="result data"),
                is_final=True,
            )

        server.set_task_handler(handler)

        result = await server.submit_task({
            "sender": "client",
            "description": "test",
            "payload": {"input": "data"},
        })
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_submit_task_generates_id(self, server):
        """未提供 task_id 时自动生成"""
        result = await server.submit_task({"sender": "client"})
        assert result["task_id"] != ""

    @pytest.mark.asyncio
    async def test_submit_task_preserves_id(self, server):
        """提供 task_id 时保留"""
        result = await server.submit_task({
            "sender": "client",
            "task_id": "custom-id-123",
        })
        assert result["task_id"] == "custom-id-123"

    def test_get_existing_task(self, server):
        """查询已存在的 Task"""
        # 先提交一个 task（同步方式绕过 async）
        task = Task(task_id="task-1", sender="test")
        server._tasks["task-1"] = task

        result = server.get_task("task-1")
        assert result is not None
        assert result["task_id"] == "task-1"

    def test_get_nonexistent_task(self, server):
        """查询不存在的 Task 返回 None"""
        result = server.get_task("nonexistent")
        assert result is None

    def test_cancel_task(self, server):
        """取消 Task"""
        task = Task(task_id="task-cancel", sender="test")
        server._tasks["task-cancel"] = task
        server._updates["task-cancel"] = []

        result = server.cancel_task("task-cancel")
        assert result is True
        assert task.status == TaskStatus.CANCELLED

    def test_cancel_nonexistent_task(self, server):
        """取消不存在的 Task 返回 False"""
        result = server.cancel_task("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_stream_task_updates(self, server):
        """流式获取 Task 更新"""
        task = Task(task_id="task-stream", sender="test")
        server._tasks["task-stream"] = task
        server._updates["task-stream"] = [
            TaskUpdate(task_id="task-stream", status=TaskStatus.SUBMITTED),
            TaskUpdate(task_id="task-stream", status=TaskStatus.WORKING),
            TaskUpdate(task_id="task-stream", status=TaskStatus.COMPLETED, is_final=True),
        ]

        updates = []
        async for update in server.stream_task_updates("task-stream"):
            updates.append(update)

        assert len(updates) == 3
        assert updates[0]["status"] == "submitted"
        assert updates[1]["status"] == "working"
        assert updates[2]["status"] == "completed"
        assert updates[2]["is_final"] is True

    @pytest.mark.asyncio
    async def test_stream_nonexistent_task(self, server):
        """流式查询不存在的 Task"""
        updates = []
        async for update in server.stream_task_updates("nonexistent"):
            updates.append(update)
        assert len(updates) == 1
        assert "error" in updates[0]

    def test_stats(self, server):
        """服务端统计"""
        # 添加一些任务
        server._tasks["t1"] = Task(task_id="t1", status=TaskStatus.WORKING)
        server._tasks["t2"] = Task(task_id="t2", status=TaskStatus.COMPLETED)
        server._tasks["t3"] = Task(task_id="t3", status=TaskStatus.SUBMITTED)

        stats = server.stats()
        assert stats["agent_id"] == "agent.server"
        assert stats["total_tasks"] == 3
        assert stats["active_tasks"] == 2  # working + submitted
        assert "chat" in stats["capabilities"]

    @pytest.mark.asyncio
    async def test_capability_validation(self, server):
        """能力验证"""
        result = await server.submit_task({
            "sender": "client",
            "capability": "nonexistent_capability",
            "payload": {},
        })
        assert result["success"] is False
        assert "CAPABILITY_NOT_SUPPORTED" in result["error_code"] or "A2A-008" in result["error_code"]

    @pytest.mark.asyncio
    async def test_capability_validation_passes(self, server):
        """支持的能力验证通过"""
        result = await server.submit_task({
            "sender": "client",
            "capability": "chat",
            "payload": {"msg": "hello"},
        })
        assert "task_id" in result
        assert result["status"] == "submitted"


# ============================================================================
# HttpTransport 测试
# ============================================================================

class TestHttpTransport:
    """HTTP 传输测试"""

    def test_http_transport_creation(self):
        """HTTP 传输创建"""
        transport = HttpTransport(
            base_url="https://example.com/a2a",
            timeout=10.0,
            signing_secret="secret",
        )
        assert transport.base_url == "https://example.com/a2a"
        assert transport.timeout == 10.0

    @pytest.mark.asyncio
    async def test_send_no_url_returns_error(self):
        """无 URL 时返回错误"""
        transport = HttpTransport()
        task = Task()
        update = await transport.send("", task)
        assert update.status == TaskStatus.FAILED
        assert "No target URL" in update.error

    @pytest.mark.asyncio
    async def test_send_without_aiohttp(self):
        """没有 aiohttp 时降级"""
        transport = HttpTransport(base_url="https://example.com")
        # 测试无 aiohttp 的情况通过 mock 来做
        # 这里只验证不会崩溃
        task = Task()
        update = await transport.send("https://example.com/tasks/submit", task)
        # aiohttp 可能存在也可能不存在，只要不崩溃就行
        assert update is not None
        assert hasattr(update, 'status')


# ============================================================================
# 协议版本协商测试
# ============================================================================

class TestProtocolNegotiation:
    """协议版本协商测试"""

    def test_exact_version_match(self):
        """精确版本匹配"""
        result = _negotiate_version(["1.0", "0.9"], ["1.0"])
        assert result == "1.0"

    def test_highest_common_version(self):
        """选择最高的共同版本"""
        result = _negotiate_version(["2.0", "1.0", "0.9"], ["1.0", "0.9"])
        assert result == "1.0"

    def test_no_common_version(self):
        """无共同版本返回 None"""
        result = _negotiate_version(["2.0", "1.5"], ["1.0", "0.9"])
        assert result is None

    def test_empty_supported(self):
        """空支持列表返回 None"""
        result = _negotiate_version([], ["1.0"])
        assert result is None

    def test_empty_requested(self):
        """空请求列表返回 None"""
        result = _negotiate_version(["1.0"], [])
        assert result is None


# ============================================================================
# 标准错误码测试
# ============================================================================

class TestA2AErrorCodes:
    """A2A 标准错误码测试"""

    def test_error_codes_defined(self):
        """常用错误码已定义"""
        assert "BAD_REQUEST" in A2A_ERROR_CODES
        assert "NOT_FOUND" in A2A_ERROR_CODES
        assert "INTERNAL_ERROR" in A2A_ERROR_CODES
        assert "UNAUTHORIZED" in A2A_ERROR_CODES
        assert "FORBIDDEN" in A2A_ERROR_CODES

    def test_error_code_format(self):
        """错误码格式正确"""
        for key, (code, http_status, message) in A2A_ERROR_CODES.items():
            assert code.startswith("A2A-")
            assert isinstance(http_status, int)
            assert 400 <= http_status <= 599
            assert isinstance(message, str)
            assert len(message) > 0

    def test_build_a2a_error(self):
        """构建标准错误响应"""
        error = _build_a2a_error("NOT_FOUND", "Task not found")
        assert error["success"] is False
        assert error["error_code"] == A2A_ERROR_CODES["NOT_FOUND"][0]
        assert error["error"] == "Task not found"
        assert error["http_status"] == 404

    def test_build_a2a_error_default_message(self):
        """默认错误消息"""
        error = _build_a2a_error("BAD_REQUEST")
        assert error["error"] == A2A_ERROR_CODES["BAD_REQUEST"][2]

    def test_build_a2a_error_unknown_key(self):
        """未知错误键回退到内部错误"""
        error = _build_a2a_error("UNKNOWN_ERROR_KEY")
        assert error["error_code"] == A2A_ERROR_CODES["INTERNAL_ERROR"][0]


# ============================================================================
# 工厂函数测试
# ============================================================================

class TestCreateA2AServer:
    """便捷工厂函数测试"""

    def test_create_server_basic(self):
        """基本创建"""
        server = create_a2a_server(
            agent_id="agent.test",
            agent_name="Test Agent",
            capabilities=["action1", "action2"],
            version="1.0.0",
        )
        assert isinstance(server, A2AProtocolServer)
        assert server.agent_card.agent_id == "agent.test"
        assert server.agent_card.name == "Test Agent"
        assert len(server.agent_card.capabilities) == 2

    def test_create_server_with_secret(self):
        """带签名密钥创建"""
        server = create_a2a_server(
            agent_id="agent.secure",
            signing_secret="my-secret",
        )
        assert server.agent_card.signature != ""
        assert server.agent_card.verify("my-secret") is True

    def test_create_server_with_handler(self):
        """带 handler 创建"""
        async def handler(task):
            return TaskUpdate(task_id=task.task_id, status=TaskStatus.COMPLETED, is_final=True)

        server = create_a2a_server(
            agent_id="agent.handler",
            task_handler=handler,
        )
        assert server._task_handler is handler


# ============================================================================
# 端到端测试（内存传输）
# ============================================================================

class TestEndToEndMemory:
    """端到端内存传输测试"""

    @pytest.mark.asyncio
    async def test_client_server_memory_e2e(self):
        """客户端-服务端通过内存传输端到端通信"""
        # 1. 创建服务端
        async def server_handler(task):
            # 模拟处理
            return TaskUpdate(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                artifact=Artifact(
                    name="response",
                    kind="text",
                    data=f"Echo: {task.description}",
                ),
                is_final=True,
            )

        server = create_a2a_server(
            agent_id="agent.server",
            agent_name="Server",
            capabilities=["echo"],
            task_handler=server_handler,
        )

        # 2. 注册到内存传输（包装 server.submit_task 返回 TaskUpdate）
        transport = MemoryTransport()

        async def server_endpoint(task):
            """将 A2AProtocolServer.submit_task 的返回值转换为 TaskUpdate"""
            task_data = {
                "task_id": task.task_id,
                "sender": task.sender,
                "description": task.description,
                "payload": task.payload,
                "trace_id": task.trace_id,
            }
            result = await server.submit_task(task_data)
            status_str = result.get("status", "submitted")
            try:
                status = TaskStatus(status_str)
            except ValueError:
                status = TaskStatus.FAILED
            # 从服务端获取完整的 task 信息（包含 artifacts）
            task_info = server.get_task(result.get("task_id", task.task_id))
            artifact = None
            if task_info and task_info.get("artifacts"):
                # 取第一个 artifact
                first = task_info["artifacts"][0]
                artifact = Artifact(
                    name=first.get("name", "output"),
                    kind=first.get("kind", "text"),
                    data=first.get("data", ""),
                )
            return TaskUpdate(
                task_id=result.get("task_id", task.task_id),
                status=status,
                error=result.get("error"),
                artifact=artifact,
                is_final=status in (
                    TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED
                ),
            )

        transport.register_handler("agent.server", server_endpoint)

        # 3. 创建客户端
        client = A2AClient(transport=transport)

        # 4. 握手
        handshake_result = await client.handshake("memory://agent.server")
        assert handshake_result["success"] is True

        # 5. 发送 Task
        card = AgentCard(agent_id="agent.server", name="Server")
        task = Task(
            sender="client",
            description="Hello, server!",
            payload={"data": "test"},
        )
        result = await client.send_task(card, task)

        # 6. 验证结果
        assert result.status == TaskStatus.COMPLETED
        assert len(result.artifacts) == 1
        assert "Echo: Hello, server!" in result.artifacts[0].data

    @pytest.mark.asyncio
    async def test_task_signing_e2e(self):
        """带签名的端到端通信"""
        secret = "shared-secret"

        async def handler(task):
            return TaskUpdate(
                task_id=task.task_id,
                status=TaskStatus.COMPLETED,
                is_final=True,
            )

        # 服务端要求鉴权
        server = A2AProtocolServer(
            agent_card=AgentCard(agent_id="agent.secure", capabilities=["test"]),
            task_handler=handler,
            signing_secret=secret,
            require_auth=True,
        )

        transport = MemoryTransport()

        async def server_endpoint(task):
            # 模拟 HTTP 端点：接收 Task 数据，验证签名后处理
            task_data = {
                "task_id": task.task_id,
                "sender": task.sender,
                "payload": task.payload,
                "signature": task.signature,
                "created_at": task.created_at,
            }
            result = await server.submit_task(task_data)
            status = TaskStatus(result["status"])
            return TaskUpdate(
                task_id=result["task_id"],
                status=status,
                is_final=status in (TaskStatus.COMPLETED, TaskStatus.FAILED),
            )

        transport.register_handler("agent.secure", server_endpoint)

        # 客户端使用相同密钥签名
        client = A2AClient(transport=transport, signing_secret=secret)
        card = AgentCard(agent_id="agent.secure")

        # 手动签名 task
        task = Task(sender="client", description="signed task")
        task.signature = sign_task(task, secret)

        result = await client.send_task(card, task)
        assert result.status == TaskStatus.COMPLETED
