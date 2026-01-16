import os
import json
import asyncio
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import httpx
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleRequest
import logging
import requests
import urllib3

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 获取凭据文件路径配置，默认读取 key/key.json
KEY_FILE_PATH = os.getenv("GCP_KEY_FILE", "key/key.json")

# 获取 GCP 区域配置，默认 global
GCP_REGION = os.getenv("GCP_REGION", "global")

# 获取是否验证 SSL 的配置
SSL_VERIFY = os.getenv("SSL_VERIFY", "true").lower() == "true"
if not SSL_VERIFY:
    logger.warning("SSL 验证已禁用！这通常仅用于 Charles/Fiddler 抓包调试。")
    # 禁用 urllib3 的警告
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 设置API请求/响应专用日志文件 - 详细日志
api_logger = logging.getLogger('api_logger')
api_logger.setLevel(logging.INFO)
api_file_handler = logging.FileHandler('api_requests.log', encoding='utf-8')
api_file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
api_logger.addHandler(api_file_handler)
api_logger.propagate = False

# 设置精简日志文件
simple_logger = logging.getLogger('simple_logger')
simple_logger.setLevel(logging.INFO)
simple_file_handler = logging.FileHandler('api_requests_simple.log', encoding='utf-8')
simple_file_handler.setFormatter(logging.Formatter('%(message)s'))
simple_logger.addHandler(simple_file_handler)
simple_logger.propagate = False

# 设置Vertex原始响应日志文件
response_logger = logging.getLogger('response_logger')
response_logger.setLevel(logging.INFO)
response_file_handler = logging.FileHandler('api_response.log', encoding='utf-8')
response_file_handler.setFormatter(logging.Formatter('%(asctime)s\n%(message)s\n'))
response_logger.addHandler(response_file_handler)
response_logger.propagate = False

app = FastAPI(title="Claude to GCP Proxy", description="代理Claude API请求到GCP Vertex AI")

# 添加 CORS 中间件，支持任何域名访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class GCPProxyServer:
    def __init__(self, service_account_path: str):
        self.service_account_path = service_account_path
        self.credentials = None
        self.project_id = None
        self.ssl_verify = SSL_VERIFY
        self.setup_credentials()

        # Claude API模型名到GCP Vertex AI模型名的映射
        self.model_mapping = {
            # Claude 3 Sonnet
            "claude-3-sonnet-20240229": "claude-3-sonnet@20240229",
            "claude-3-sonnet": "claude-3-sonnet@20240229",

            # Claude 3 Haiku
            "claude-3-haiku-20240307": "claude-3-haiku@20240307",
            "claude-3-haiku": "claude-3-haiku@20240307",

            # Claude 3.5 Sonnet
            "claude-3-5-sonnet-20241022": "claude-3-5-sonnet@20241022",
            "claude-3-5-sonnet": "claude-3-5-sonnet@20241022",

            # Claude 3.5 Haiku
            "claude-3-5-haiku-20241022": "claude-3-5-haiku@20241022",
            "claude-3-5-haiku": "claude-3-5-haiku@20241022",

            # Claude 4 Sonnet
            "claude-4-sonnet-20250514": "claude-sonnet-4@20250514",
            "claude-sonnet-4-20250514": "claude-sonnet-4@20250514",
            "claude-4-sonnet": "claude-sonnet-4@20250514",
            "claude-sonnet-4": "claude-sonnet-4@20250514",

            # Claude 4.5 Sonnet
            "claude-sonnet-4-5-20250929": "claude-sonnet-4-5@20250929",
            "claude-4-5-sonnet-20250929": "claude-sonnet-4-5@20250929",
            "claude-sonnet-4-5": "claude-sonnet-4-5@20250929",

            # Claude 4.5 Haiku
            "claude-haiku-4-5-20251001": "claude-haiku-4-5@20251001",
            "claude-4-5-haiku-20251001": "claude-haiku-4-5@20251001",
            "claude-haiku-4-5": "claude-haiku-4-5@20251001",

            # Claude 4.5 Opus
            "claude-opus-4-5-20251101": "claude-opus-4-5@20251101",
            "claude-4-5-opus-20251101": "claude-opus-4-5@20251101",
            "claude-opus-4-5": "claude-opus-4-5@20251101",
        }

        # 默认使用最新的可用模型
        self.default_model = "claude-sonnet-4-5@20250929"

    def log_simple_conversation(self, claude_request: Dict[str, Any], claude_response: Dict[str, Any] = None):
        """记录精简格式的对话日志"""
        try:
            log_entries = []

            # 首先记录模型信息
            model_name = claude_request.get('model', 'unknown')
            log_entries.append(f"model：{model_name}")

            # 处理messages中的对话
            messages = claude_request.get('messages', [])
            for message in messages:
                role = message.get('role', '')
                content = message.get('content', '')

                # 提取文本内容
                if isinstance(content, list):
                    # 处理结构化内容
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get('type') == 'text':
                            text_parts.append(part.get('text', ''))
                    content_text = ''.join(text_parts)
                elif isinstance(content, str):
                    content_text = content
                else:
                    content_text = str(content)

                # 添加角色和内容
                if role == 'user':
                    # 移除换行符并只保留前100个字符
                    cleaned_content = content_text.replace('\n', ' ').replace('\r', ' ')
                    truncated_content = cleaned_content[:100]
                    log_entries.append(f"user：{truncated_content}")
                elif role == 'assistant':
                    # 移除换行符并只保留前200个字符
                    cleaned_content = content_text.replace('\n', ' ').replace('\r', ' ')
                    truncated_content = cleaned_content[:200]
                    log_entries.append(f"assistant：{truncated_content}")

            # 处理tools信息
            if 'tools' in claude_request:
                tool_names = []
                tools = claude_request['tools']
                if isinstance(tools, list):
                    for tool in tools:
                        if isinstance(tool, dict):
                            name = tool.get('name', '')
                            if name:
                                tool_names.append(name)

                if tool_names:
                    tools_str = ' / '.join(tool_names)
                    log_entries.append(f"tools：{tools_str}")

            # 处理system信息
            if 'system' in claude_request:
                system_content = claude_request['system']
                if isinstance(system_content, str):
                    system_preview = system_content[:30]
                    log_entries.append(f"system：{system_preview}")

            # 如果有响应，添加assistant的响应内容
            if claude_response:
                if 'content' in claude_response:
                    response_content = claude_response['content']
                    if isinstance(response_content, list):
                        # 处理结构化响应内容
                        text_parts = []
                        for part in response_content:
                            if isinstance(part, dict) and part.get('type') == 'text':
                                text_parts.append(part.get('text', ''))
                        response_text = ''.join(text_parts)
                    elif isinstance(response_content, str):
                        response_text = response_content
                    else:
                        response_text = str(response_content)

                    if response_text:
                        # 移除换行符并只保留前200个字符
                        cleaned_response = response_text.replace('\n', ' ').replace('\r', ' ')
                        truncated_response = cleaned_response[:200]
                        log_entries.append(f"assistant：{truncated_response}")

                # 添加 usage 信息
                if 'usage' in claude_response:
                    usage = claude_response['usage']
                    # 参考其他项目的逻辑：输入 Token = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
                    cache_read = usage.get('cache_read_input_tokens', 0)
                    cache_create = usage.get('cache_creation_input_tokens', 0)
                    input_tokens = usage.get('input_tokens', 0) + cache_read + cache_create
                    output_tokens = usage.get('output_tokens', 0)

                    usage_str = f"usage：input={input_tokens}"
                    if cache_read:
                        usage_str += f"(cache_read={cache_read})"
                    if cache_create:
                        usage_str += f"(cache_create={cache_create})"
                    usage_str += f", output={output_tokens}, total={input_tokens + output_tokens}"
                    log_entries.append(usage_str)

            # 记录到精简日志文件
            if log_entries:
                for entry in log_entries:
                    simple_logger.info(entry)
                simple_logger.info("-----------------\n")  # 分割线分隔不同的请求

        except Exception as e:
            logger.error(f"记录精简日志失败: {e}")

    def setup_credentials(self):
        """设置GCP凭据"""
        try:
            with open(self.service_account_path, 'r') as f:
                service_account_info = json.load(f)

            self.project_id = service_account_info['project_id']
            self.credentials = service_account.Credentials.from_service_account_file(
                self.service_account_path,
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
            logger.info(f"GCP凭据设置成功，项目ID: {self.project_id}")
        except Exception as e:
            logger.error(f"设置GCP凭据失败: {e}")
            raise

    def get_access_token(self) -> str:
        """获取GCP访问令牌"""
        try:
            # 刷新凭据获取访问令牌
            # 使用自定义 session 以支持禁用 SSL 验证（用于 Charles 抓包）
            session = requests.Session()
            session.verify = self.ssl_verify

            # 如果挂了代理，requests 也会尝试使用环境变量中的代理设置
            # Charles 开启后通常会自动设置系统代理

            self.credentials.refresh(GoogleRequest(session=session))
            return self.credentials.token
        except Exception as e:
            logger.error(f"获取访问令牌失败: {e}")
            raise

    def get_vertex_model_name(self, claude_model: str) -> str:
        """将Claude API模型名映射到GCP Vertex AI模型名"""
        # 清理模型名（去除首尾空白字符）
        claude_model = claude_model.strip() if claude_model else ""

        if claude_model in self.model_mapping:
            vertex_model = self.model_mapping[claude_model]
            logger.info(f"模型映射: {claude_model} -> {vertex_model}")
        else:
            vertex_model = self.default_model
            logger.warning(f"未知模型 '{claude_model}'，使用默认模型: {vertex_model}")
        return vertex_model

    def _convert_vertex_sse_to_claude(self, line: str) -> Optional[str]:
        """将Vertex AI的SSE格式转换为Claude API格式"""
        try:
            if line.startswith('event: '):
                event_type = line[7:].strip()
                # 过滤掉不需要的事件类型
                if event_type in ['vertex_event', 'ping']:
                    return None
                # 保留重要的事件
                elif event_type in ['message_start', 'content_block_start', 'content_block_delta',
                                   'content_block_stop', 'message_delta', 'message_stop']:
                    return f"{line}\n"
                else:
                    return None

            elif line.startswith('data: '):
                data_part = line[6:].strip()

                # 处理结束标记
                if data_part == '[DONE]':
                    return f"{line}\n\n"

                # 尝试解析JSON数据
                try:
                    data_json = json.loads(data_part)
                    event_type = data_json.get('type', '')

                    # 过滤掉不需要的数据事件
                    if event_type in ['vertex_event', 'ping']:
                        return None

                    # 保留重要的数据事件
                    elif event_type in ['message_start', 'content_block_start', 'content_block_delta',
                                       'content_block_stop', 'message_delta', 'message_stop']:
                        return f"{line}\n\n"
                    else:
                        return None

                except json.JSONDecodeError:
                    # 如果无法解析JSON，保留原始数据
                    return f"{line}\n\n"

            # 其他类型的行直接过滤掉
            return None

        except Exception as e:
            logger.warning(f"SSE转换失败: {e}")
            # 出错时保留原始行
            return f"{line}\n"

    def _clean_tools(self, tools: list) -> list:
        """清理工具定义，移除Vertex AI不支持的字段"""
        cleaned_tools = []
        for tool in tools:
            if isinstance(tool, dict):
                # 创建工具的副本
                cleaned_tool = tool.copy()

                # 移除Vertex AI不支持的字段
                # 1. 移除 input_examples 字段
                if 'input_examples' in cleaned_tool:
                    cleaned_tool.pop('input_examples')

                # 2. 如果有其他嵌套的不支持字段，也要清理
                if 'input_schema' in cleaned_tool and isinstance(cleaned_tool['input_schema'], dict):
                    schema = cleaned_tool['input_schema']
                    # 移除 schema 中可能的自定义扩展字段
                    if '$comment' in schema:
                        schema.pop('$comment')

                cleaned_tools.append(cleaned_tool)
            else:
                cleaned_tools.append(tool)

        return cleaned_tools

    def claude_to_vertex_request(self, claude_request: Dict[str, Any]) -> Dict[str, Any]:
        """将Claude API请求转换为Vertex AI请求格式"""
        try:
            # 提取Claude请求中的基本参数
            messages = claude_request.get('messages', [])
            model = claude_request.get('model', 'claude-3-sonnet-20240229')
            max_tokens = claude_request.get('max_tokens', 4096)

            # 构建Vertex AI的请求格式
            vertex_request = {
                "anthropic_version": "vertex-2023-10-16",
                "max_tokens": max_tokens,
                "messages": messages
            }

            # 只有客户端传了 temperature 才转发，不设默认值
            if 'temperature' in claude_request:
                vertex_request['temperature'] = claude_request['temperature']

            # 处理system消息
            if 'system' in claude_request:
                vertex_request['system'] = claude_request['system']

            # 处理tools相关 - 清理不支持的字段
            if 'tools' in claude_request:
                original_tools = claude_request['tools']
                cleaned_tools = self._clean_tools(original_tools)
                vertex_request['tools'] = cleaned_tools

                # 记录清理的工具数量
                logger.info(f"清理工具定义: 原始 {len(original_tools)} 个工具")

            if 'tool_choice' in claude_request:
                vertex_request['tool_choice'] = claude_request['tool_choice']

            # 处理其他可选参数
            if 'top_p' in claude_request:
                vertex_request['top_p'] = claude_request['top_p']

            if 'top_k' in claude_request:
                vertex_request['top_k'] = claude_request['top_k']

            if 'stop_sequences' in claude_request:
                vertex_request['stop_sequences'] = claude_request['stop_sequences']

            if 'stream' in claude_request:
                vertex_request['stream'] = claude_request['stream']

            # 处理metadata
            if 'metadata' in claude_request:
                vertex_request['metadata'] = claude_request['metadata']

            logger.info(f"转换请求参数: max_tokens={max_tokens}, temperature={vertex_request.get('temperature', '未设置')}, "
                       f"system={'是' if 'system' in claude_request else '否'}, "
                       f"tools={'是' if 'tools' in claude_request else '否'}")

            return vertex_request
        except Exception as e:
            logger.error(f"转换请求格式失败: {e}")
            raise

    def vertex_to_claude_response(self, vertex_response: Dict[str, Any]) -> Dict[str, Any]:
        """将Vertex AI响应转换为Claude API响应格式"""
        try:
            # 直接返回Vertex AI的响应，因为它应该已经是Claude格式
            return vertex_response
        except Exception as e:
            logger.error(f"转换响应格式失败: {e}")
            raise

    async def forward_to_vertex(self, claude_request: Dict[str, Any]):
        """转发请求到Vertex AI，支持流式和非流式响应"""
        try:
            logger.info("开始处理请求转发")

            # 获取访问令牌
            try:
                access_token = self.get_access_token()
                logger.info("成功获取访问令牌")
            except Exception as e:
                logger.error(f"获取访问令牌失败: {type(e).__name__}: {e}")
                raise HTTPException(status_code=500, detail=f"认证失败: {str(e)}")

            # 转换请求格式
            try:
                vertex_request = self.claude_to_vertex_request(claude_request)
                logger.info("成功转换请求格式")
            except Exception as e:
                logger.error(f"转换请求格式失败: {type(e).__name__}: {e}")
                raise HTTPException(status_code=400, detail=f"请求格式错误: {str(e)}")

            # 构建Vertex AI API端点
            region = GCP_REGION

            # 从请求中获取模型名并映射到GCP模型名
            requested_model = claude_request.get('model', 'claude-3-sonnet-20240229')
            vertex_model_name = self.get_vertex_model_name(requested_model)

            # 检查是否是流式请求
            is_streaming = claude_request.get('stream', False)
            logger.info(f"请求类型: {'流式' if is_streaming else '非流式'}")

            # 根据是否流式选择端点
            predict_method = "streamRawPredict" if is_streaming else "rawPredict"

            # global 区域使用不带前缀的域名
            if region == "global":
                endpoint = f"https://aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{region}/publishers/anthropic/models/{vertex_model_name}:{predict_method}"
            else:
                endpoint = f"https://{region}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{region}/publishers/anthropic/models/{vertex_model_name}:{predict_method}"

            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }

            if is_streaming:
                # 流式请求处理
                logger.info("处理流式请求")

                # 记录原始Claude请求到日志文件
                api_logger.info("=" * 80)
                api_logger.info("📥 收到Claude API请求:")
                api_logger.info(json.dumps(claude_request, ensure_ascii=False, indent=2))

                # 记录转换后的Vertex AI请求到日志文件
                api_logger.info("🔄 转换后的Vertex AI请求:")
                api_logger.info(json.dumps(vertex_request, ensure_ascii=False, indent=2))
                api_logger.info(f"🎯 模型映射: {requested_model} -> {vertex_model_name}")
                api_logger.info(f"🌐 请求端点: {endpoint}")

                # 记录精简格式的对话日志（仅请求部分，不包括响应）
                self.log_simple_conversation(claude_request)

                return self._handle_streaming_request(endpoint, headers, vertex_request, claude_request)
            else:
                # 非流式请求处理
                logger.info("开始发送非流式请求到Vertex AI")

                # 记录原始Claude请求到日志文件
                api_logger.info("=" * 80)
                api_logger.info("📥 收到Claude API请求:")
                api_logger.info(json.dumps(claude_request, ensure_ascii=False, indent=2))

                # 记录转换后的Vertex AI请求到日志文件
                api_logger.info("🔄 转换后的Vertex AI请求:")
                api_logger.info(json.dumps(vertex_request, ensure_ascii=False, indent=2))
                api_logger.info(f"🎯 模型映射: {requested_model} -> {vertex_model_name}")
                api_logger.info(f"🌐 请求端点: {endpoint}")

                try:
                    async with httpx.AsyncClient(verify=self.ssl_verify) as client:
                        response = await client.post(
                            endpoint,
                            json=vertex_request,
                            headers=headers,
                            timeout=60.0
                        )

                        logger.info(f"Vertex AI响应状态码: {response.status_code}")
                        api_logger.info(f"📊 Vertex AI响应状态码: {response.status_code}")

                        if response.status_code == 200:
                            try:
                                vertex_response = response.json()
                                logger.info("成功解析Vertex AI响应")

                                # 记录GCP原始响应到日志文件
                                api_logger.info("📤 Vertex AI原始响应:")
                                api_logger.info(json.dumps(vertex_response, ensure_ascii=False, indent=2))

                                # 记录Vertex原始响应到专用日志文件
                                response_logger.info("=" * 80)
                                response_logger.info(json.dumps(vertex_response, ensure_ascii=False, indent=2))

                                # 转换响应格式
                                final_response = self.vertex_to_claude_response(vertex_response)

                                # 打印 usage 到终端
                                if 'usage' in final_response:
                                    usage = final_response['usage']
                                    input_total = usage.get('input_tokens', 0) + usage.get('cache_read_input_tokens', 0) + usage.get('cache_creation_input_tokens', 0)
                                    logger.info(f"响应 Usage: input={input_total} (read={usage.get('cache_read_input_tokens',0)}, create={usage.get('cache_creation_input_tokens',0)}), output={usage.get('output_tokens', 0)}")

                                # 记录最终返回给客户端的响应到日志文件
                                api_logger.info("✅ 最终返回给客户端的响应:")
                                api_logger.info(json.dumps(final_response, ensure_ascii=False, indent=2))
                                api_logger.info("=" * 80 + "\n")

                                # 记录精简格式的对话日志
                                self.log_simple_conversation(claude_request, final_response)

                                return final_response
                            except Exception as e:
                                logger.error(f"解析响应失败: {type(e).__name__}: {e}")
                                api_logger.info(f"❌ 响应解析失败: {type(e).__name__}: {e}")
                                api_logger.info("=" * 80 + "\n")
                                raise HTTPException(status_code=500, detail=f"响应解析错误: {str(e)}")
                        else:
                            error_text = response.text
                            logger.error(f"Vertex AI请求失败: {response.status_code}, {error_text}")
                            api_logger.info(f"❌ Vertex AI请求失败: {response.status_code}")
                            api_logger.info(f"错误详情: {error_text}")
                            api_logger.info("=" * 80 + "\n")
                            raise HTTPException(status_code=response.status_code, detail=error_text)

                except httpx.RequestError as e:
                    logger.error(f"HTTP请求错误: {type(e).__name__}: {e}")
                    raise HTTPException(status_code=500, detail=f"网络请求失败: {str(e)}")
                except httpx.TimeoutException as e:
                    logger.error(f"请求超时: {e}")
                    raise HTTPException(status_code=504, detail="请求超时")

        except HTTPException:
            # 重新抛出HTTP异常
            raise
        except Exception as e:
            logger.error(f"转发到Vertex AI失败: {type(e).__name__}: {e}")
            raise HTTPException(status_code=500, detail=f"内部服务器错误: {str(e)}")

    async def count_tokens(self, claude_request: Dict[str, Any]):
        """转发 Token 计数请求到 Vertex AI"""
        try:
            # 获取访问令牌
            access_token = self.get_access_token()

            # 获取映射后的模型名
            requested_model = claude_request.get('model', '')
            vertex_model_name = self.get_vertex_model_name(requested_model)

            # 构建 Vertex AI 请求
            vertex_request = {
                "model": vertex_model_name,
                "messages": claude_request.get('messages', [])
            }

            # 处理 system 消息 (如果有)
            if 'system' in claude_request:
                vertex_request['system'] = claude_request['system']

            # 处理 tools (如果有)
            if 'tools' in claude_request:
                vertex_request['tools'] = self._clean_tools(claude_request['tools'])

            # Token 计数目前支持的区域有限，如果当前是 global，显式使用 us-central1
            region = GCP_REGION
            if region == "global":
                # 切换到支持 count-tokens 的区域
                count_region = "us-central1"
                endpoint = f"https://{count_region}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{count_region}/publishers/anthropic/models/count-tokens:rawPredict"
            else:
                endpoint = f"https://{region}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{region}/publishers/anthropic/models/count-tokens:rawPredict"

            logger.info(f"发送 Token 计数请求到端点: {endpoint} (模型: {vertex_model_name})")

            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }

            async with httpx.AsyncClient(verify=self.ssl_verify) as client:
                response = await client.post(
                    endpoint,
                    json=vertex_request,
                    headers=headers,
                    timeout=30.0
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Token 计数成功: {result}")
                    return result
                else:
                    error_text = response.text
                    logger.error(f"Token 计数失败: {response.status_code}, {error_text}")
                    raise HTTPException(status_code=response.status_code, detail=error_text)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Token 计数转发失败: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def _handle_streaming_request(self, endpoint: str, headers: Dict[str, str], vertex_request: Dict[str, Any], claude_request: Dict[str, Any]):
        """处理流式请求 - 异步生成器"""
        try:
            logger.info("开始处理流式请求")
            async with httpx.AsyncClient(timeout=120.0, verify=self.ssl_verify) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    json=vertex_request,
                    headers=headers,
                ) as response:
                    logger.info(f"流式响应状态码: {response.status_code}")
                    api_logger.info(f"📊 Vertex AI响应状态码: {response.status_code}")

                    if response.status_code != 200:
                        logger.error(f"流式请求失败: {response.status_code}")
                        try:
                            error_text = await response.aread()
                            error_detail = error_text.decode() if error_text else "未知错误"
                        except:
                            error_detail = f"HTTP {response.status_code} 错误"

                        logger.error(f"流式请求失败详情: {error_detail}")

                        api_logger.info(f"❌ Vertex AI请求失败: {response.status_code}")
                        api_logger.info(f"错误详情: {error_detail}")
                        api_logger.info("=" * 80 + "\n")

                        error_data = {
                            "error": {
                                "type": "api_error",
                                "message": error_detail
                            }
                        }
                        yield f"data: {json.dumps(error_data)}\n\n"
                        yield "data: [DONE]\n\n"
                        return

                    # 检查响应Content-Type
                    content_type = response.headers.get('content-type', '')
                    logger.info(f"响应Content-Type: {content_type}")

                    if 'text/event-stream' in content_type:
                        # GCP返回的是SSE格式，需要转换为Claude API格式
                        logger.info("处理SSE格式响应并转换为Claude API格式")

                        current_event = None
                        pending_event_line = None

                        # 用于聚合响应信息
                        full_response_text = ""
                        final_usage = {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0
                        }

                        response_logger.info("=" * 80)
                        async for line in response.aiter_lines():
                            line_str = line.strip() if line else ""

                            # 🔍 打印 Vertex 原始响应行（用于调试 cache 数据）
                            if line_str:
                                logger.info(f"[Vertex原始] {line_str[:500]}")
                                # 记录到专用响应日志文件
                                response_logger.info(line_str)

                            if line_str.startswith('event:'):
                                # 处理事件行
                                event_type = line_str[6:].strip()
                                if event_type in ['message_start', 'content_block_start', 'content_block_delta',
                                                'content_block_stop', 'message_delta', 'message_stop']:
                                    current_event = event_type
                                    pending_event_line = line_str
                                else:
                                    current_event = None
                                    pending_event_line = None

                            elif line_str.startswith('data:'):
                                # 处理数据行
                                data_part = line_str[5:].strip()

                                if data_part == '[DONE]':
                                    yield f"{line_str}\n\n"
                                    break

                                if current_event:
                                    try:
                                        # 验证JSON并过滤无用事件
                                        data_json = json.loads(data_part)
                                        if data_json.get('type') not in ['vertex_event', 'ping']:
                                            # 发送完整的事件（event行 + data行）
                                            if pending_event_line:
                                                yield f"{pending_event_line}\n"
                                                pending_event_line = None

                                            yield f"{line_str}\n\n"

                                            # 聚合信息用于日志记录
                                            if current_event == 'message_start':
                                                usage = data_json.get('message', {}).get('usage', {})
                                                # message_start 包含初始的 usage 信息
                                                for k in ['input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens']:
                                                    if k in usage:
                                                        final_usage[k] = usage[k]
                                            elif current_event == 'content_block_delta':
                                                delta = data_json.get('delta', {})
                                                if delta.get('type') == 'text_delta':
                                                    full_response_text += delta.get('text', '')
                                            elif current_event == 'message_delta':
                                                usage = data_json.get('usage', {})
                                                # message_delta 包含该消息最终的 output_tokens 统计
                                                if 'output_tokens' in usage:
                                                    final_usage['output_tokens'] = usage['output_tokens']

                                    except json.JSONDecodeError:
                                        # 如果JSON解析失败，但事件类型正确，仍然发送
                                        if pending_event_line:
                                            yield f"{pending_event_line}\n"
                                            pending_event_line = None
                                        yield f"{line_str}\n\n"

                        # 记录流式响应聚合结果
                        api_logger.info("✅ 流式响应完成，聚合结果:")
                        # 计算总输入 Token 用于日志展示
                        input_tokens_total = (
                            final_usage.get("input_tokens", 0) +
                            final_usage.get("cache_read_input_tokens", 0) +
                            final_usage.get("cache_creation_input_tokens", 0)
                        )
                        display_usage = final_usage.copy()
                        display_usage["_total_input_tokens"] = input_tokens_total

                        # 在终端打印 usage 信息
                        logger.info(f"聚合 Usage: {json.dumps(display_usage)}")
                        api_logger.info(f"Usage: {json.dumps(display_usage)}")

                        # 记录到精简日志
                        self.log_simple_conversation(claude_request, {
                            "content": [{"type": "text", "text": full_response_text}],
                            "usage": final_usage
                        })

                    else:
                        # GCP可能返回的是JSON流或分块JSON
                        logger.info("处理JSON流响应")
                        buffer = ""
                        async for chunk in response.aiter_bytes():
                            if chunk:
                                buffer += chunk.decode('utf-8', errors='ignore')

                                # 尝试解析JSON对象
                                while '\n' in buffer:
                                    line, buffer = buffer.split('\n', 1)
                                    line = line.strip()
                                    if line:
                                        try:
                                            # 验证是否为有效JSON
                                            json_obj = json.loads(line)
                                            yield f"data: {json.dumps(json_obj)}\n\n"
                                        except json.JSONDecodeError:
                                            # 如果不是JSON，可能是SSE格式的数据
                                            if line.startswith('data:') or line.startswith('event:'):
                                                yield f"{line}\n"
                                            else:
                                                yield f"data: {json.dumps({'type': 'text', 'content': line})}\n\n"

                    # 发送结束标记
                    yield "data: [DONE]\n\n"
                    logger.info("流式响应处理完成")
                    api_logger.info("✅ 流式响应处理完成")
                    api_logger.info("=" * 80 + "\n")

        except Exception as e:
            logger.error(f"流式处理失败: {type(e).__name__}: {e}")
            api_logger.info(f"❌ 流式处理失败: {type(e).__name__}: {e}")
            api_logger.info("=" * 80 + "\n")
            error_data = {
                "error": {
                    "type": "internal_error",
                    "message": str(e)
                }
            }
            yield f"data: {json.dumps(error_data)}\n\n"
            yield "data: [DONE]\n\n"

# 初始化代理服务器
proxy_server = GCPProxyServer(KEY_FILE_PATH)

@app.post("/v1/messages")
async def proxy_messages(request: Request):
    """代理Claude messages API，支持流式和非流式响应"""
    try:
        # 获取原始请求体
        body = await request.json()
        is_streaming = body.get('stream', False)

        logger.info(f"收到Claude API请求: {body.get('model', 'unknown')}, "
                   f"流式: {'是' if is_streaming else '否'}")

        # 打印原始请求体结构（prompt字段截断显示）
        print("\n" + "="*80)
        print("【原始客户端请求体】")
        print("="*80)
        body_display = body.copy()

        # 处理messages中的content字段，如果是prompt则截断
        if 'messages' in body_display:
            for msg in body_display['messages']:
                if isinstance(msg.get('content'), str):
                    content = msg['content']
                    if len(content) > 100:
                        msg['content'] = content[:100] + f"... [共 {len(content)} 字符]"

        # 处理tools中的description字段，截断显示
        if 'tools' in body_display:
            for tool in body_display['tools']:
                if 'description' in tool:
                    desc = tool['description']
                    if len(desc) > 100:
                        tool['description'] = desc[:100] + f"... [共 {len(desc)} 字符]"

        # 打印完整的结构化请求体
        print(json.dumps(body_display, ensure_ascii=False, indent=2))
        print("="*80 + "\n")

        # 转发到Vertex AI
        response = await proxy_server.forward_to_vertex(body)

        if is_streaming:
            # 流式响应
            logger.info("返回流式响应")
            return StreamingResponse(
                response,
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "X-Accel-Buffering": "no",  # 禁用Nginx缓冲
                    "Transfer-Encoding": "chunked"  # 确保分块传输
                }
            )
        else:
            # 非流式响应
            logger.info("成功转发请求并获得响应")
            return response

    except Exception as e:
        logger.error(f"代理请求失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/messages/count_tokens")
async def count_tokens(request: Request):
    """代理 Claude Token 计数 API"""
    try:
        body = await request.json()
        logger.info(f"收到 Token 计数请求: {body.get('model', 'unknown')}")

        # 转发到 Vertex AI
        result = await proxy_server.count_tokens(body)
        return result
    except Exception as e:
        logger.error(f"Token 计数代理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/models")
async def list_models():
    """返回可用模型列表"""
    models_data = []

    # 从模型映射中生成模型列表
    for claude_model, vertex_model in proxy_server.model_mapping.items():
        models_data.append({
            "id": claude_model,
            "object": "model",
            "created": 1677610602,
            "owned_by": "anthropic",
            "vertex_model": vertex_model  # 显示映射到的GCP模型
        })

    # 添加默认模型信息
    models_data.append({
        "id": "default",
        "object": "model",
        "created": 1677610602,
        "owned_by": "anthropic",
        "vertex_model": proxy_server.default_model,
        "description": "默认模型，用于未知模型名"
    })

    return {
        "object": "list",
        "data": models_data
    }

@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy", "project_id": proxy_server.project_id}

@app.get("/")
async def root():
    """根端点"""
    return {
        "message": "Claude to GCP Proxy Server",
        "status": "running",
        "endpoints": {
            "messages": "/v1/messages",
            "models": "/v1/models",
            "health": "/health"
        }
    }

if __name__ == "__main__":
    logger.info("启动Claude to GCP代理服务器...")
    logger.info("服务已启动，支持通过 IP 或任何绑定的域名访问")
    logger.info("示例环境变量: export ANTHROPIC_BASE_URL=http://your-domain.com:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
