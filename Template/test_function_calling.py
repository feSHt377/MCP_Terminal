"""
Function Calling 测试脚本
测试 Ollama 模型是否能正确调用定义的工具函数
"""

import json
import sys
import time
import requests
from typing import Any, Dict, List, Optional, Tuple
from tools import execute_tool, get_tool_schema_list


# Windows 的旧控制台默认 GBK，无法输出脚本中的 emoji 和 UTF-8 文本。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


class FunctionCallingTester:
    """Function Calling 测试器"""
    
    def __init__(self, api_url: str = "http://100.64.0.13:11438",
                 model: str = "qwen3.6:27b"):
        self.api_url = api_url.rstrip("/")
        self.model = model
        self.session = requests.Session()
        self.session.trust_env = False  # 禁用代理
        self.call_count = 0
        self.success_count = 0
        self.failed_count = 0
        self.round_times: List[Dict] = []  # 每轮响应时间记录
        self.test_case_times: List[Dict] = []  # 每个测试用例的耗时
        
    def test_function_calling(self, prompt: str, tools: Optional[List[Dict]] = None,
                              max_rounds: int = 5, model_options: Optional[Dict] = None) -> Dict:
        """
        测试模型的 Function Calling 能力（支持多轮工具调用链）
        
        Args:
            prompt: 用户提示词
            tools: 工具定义列表
            max_rounds: 最大工具调用轮数（防止无限循环）
            
        Returns:
            测试结果
        """
        if tools is None:
            tools = get_tool_schema_list()
            
        print(f"\n{'='*50}")
        print(f"测试提示词: {prompt}")
        print(f"{'='*50}")
        
        # 构建消息历史
        system_prompt = (
            "你是一个智能助手，拥有多个工具可以帮助用户完成任务。"
            "当用户的请求适合使用工具时，请主动调用相应的工具。"
            "不要直接回答可以用工具完成的任务，而是先调用工具获取结果。"
            "可用的工具包括：弹窗显示信息、数学计算、获取时间、保存日志等。"
        )
        messages: List[Dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        tool_schemas = tools
        
        all_tool_calls = []  # 记录所有轮次的工具调用
        all_tool_results = []
        round_records = []  # 每轮耗时记录
        overall_start = time.time()
        
        completed = False
        # 多轮工具调用循环
        for round_num in range(1, max_rounds + 1):
            # 发送请求，让模型决定调用哪个工具（流式）
            print(f"\n{'~'*50}")
            print(f"🔄 第 {round_num} 轮: 获取模型响应...")
            print(f"{'~'*50}")
            
            round_start = time.time()
            response, tool_calls, response_time = self._send_streaming_request(
                messages, tool_schemas, model_options=model_options
            )
            
            if not response:
                return {"status": "error", "message": "模型请求失败", "timing": {"rounds": round_records}}
            
            # 检查模型是否决定调用工具
            if not tool_calls:
                # 模型没有调用工具，对话结束
                round_elapsed = time.time() - round_start
                round_records.append({
                    "round": round_num,
                    "response_time": round_elapsed,
                    "tool_count": 0
                })
                print(f"\n⏱  第 {round_num} 轮总耗时: {round_elapsed:.2f} 秒（无工具调用）")
                completed = True
                break
            
            print(f"\n✅ 模型决定调用 {len(tool_calls)} 个工具")
            self.call_count += len(tool_calls)
            all_tool_calls.extend(tool_calls)
            
            # 将模型的 tool_calls 加入消息历史
            messages.append({
                "role": "assistant",
                "tool_calls": tool_calls
            })
            
            # 执行工具调用
            print("\n" + "🔧 " + "-" * 48)
            print("   工具执行阶段:")
            print("-" * 52)
            
            for tool_call in tool_calls:
                result = self._execute_tool(tool_call)
                all_tool_results.append(result)
                
                # 将工具结果加入消息历史
                tool_id = tool_call.get("id", f"call_{len(messages)}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": json.dumps(result, ensure_ascii=False)
                })
                
                if result["status"] == "success":
                    self.success_count += 1
                    print(f"   ✅ 工具执行成功: {tool_call['function']['name']}")
                else:
                    self.failed_count += 1
                    print(f"   ❌ 工具执行失败: {tool_call['function']['name']}")
            
            print("-" * 52)
            
            # 记录本轮耗时
            round_elapsed = time.time() - round_start
            round_records.append({
                "round": round_num,
                "response_time": round_elapsed,
                "model_response_time": response_time,
                "tool_count": len(tool_calls)
            })
            print(f"⏱  第 {round_num} 轮总耗时: {round_elapsed:.2f} 秒")
            
            self.round_times = round_records
        
        # 总耗时
        overall_elapsed = time.time() - overall_start
        
        # 打印耗时汇总
        print(f"\n{'='*50}")
        print("📊 耗时汇总")
        print(f"{'='*50}")
        for rec in round_records:
            print(f"  第 {rec['round']} 轮: {rec['response_time']:.2f} 秒 "
                  f"(模型响应: {rec.get('model_response_time', 0):.2f} 秒, "
                  f"调用 {rec['tool_count']} 个工具)")
        print(f"  ─────────────────────────")
        print(f"  总耗时: {overall_elapsed:.2f} 秒")
        print(f"{'='*50}\n")
        
        return {
            "status": "success" if completed else "error",
            "message": "任务完成" if completed else f"达到最大轮数限制 ({max_rounds})，测试已停止",
            "tool_calls": all_tool_calls,
            "tool_results": all_tool_results,
            "total_rounds": len(round_records),
            "timing": {
                "total_elapsed": round(overall_elapsed, 2),
                "rounds": round_records
            }
        }
        
    def _send_streaming_request(self, messages: List[Dict], tool_schemas: List[Dict],
                                model_options: Optional[Dict] = None) -> Tuple[Optional[Dict], List[Dict], float]:
        """发送流式请求到 Ollama，实时输出模型响应
        
        Args:
            messages: 完整消息历史（包含用户输入、助手回复、工具结果等）
            tool_schemas: 工具 Schema 列表（已过滤 point 字段）
            
        Returns:
            (full_response, all_tool_calls, elapsed_seconds)
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tool_schemas,
            "stream": True  # 启用流式输出
        }
        if model_options:
            payload["options"] = model_options
        
        start_time = time.time()
        
        try:
            response = self.session.post(
                f"{self.api_url}/api/chat",
                json=payload,
                timeout=180,
                stream=True,
            )
            
            if response.status_code != 200:
                print(f"请求失败: {response.status_code} - {response.text}")
                return None, [], 0.0
            
            # 收集流式响应
            full_response = {}
            accumulated_content = ""
            all_tool_calls = []
            
            # 打印模型回复的边框
            print("\n" + "📥 " + "=" * 48)
            print("   模型响应 (流式输出):")
            print("┌" + "─" * 48 + "┐")
            
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                
                # 跳过空行
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # 合并 message 字段
                message = chunk.get("message", {})
                if not full_response.get("message"):
                    full_response["message"] = {}
                
                # 累加内容并实时输出（使用绿色高亮）
                content = message.get("content", "")
                if content:
                    accumulated_content += content
                    print(f"\033[92m   {content}\033[0m", end="", flush=True)
                
                # 收集 tool_calls 并实时显示
                chunk_tool_calls = message.get("tool_calls", [])
                for tc in chunk_tool_calls:
                    # 合并到已有的 tool_calls 或新增
                    self._merge_tool_call(all_tool_calls, tc)
                    # 实时显示 tool_calls JSON（黄色高亮）
                    print(f"\n\033[93m   🔧 Tool Call: {json.dumps(tc, ensure_ascii=False)}\033[0m", flush=True)
                
                # 更新完整响应
                if chunk.get("done"):
                    full_response["done"] = True
                if message.get("role"):
                    full_response["message"]["role"] = message["role"]
                if accumulated_content:
                    full_response["message"]["content"] = accumulated_content
                if all_tool_calls:
                    full_response["message"]["tool_calls"] = all_tool_calls
            
            # 打印模型回复的结束边框
            print()
            print("└" + "─" * 48 + "┘")
            
            elapsed = time.time() - start_time
            print(f"⏱  响应耗时: {elapsed:.2f} 秒")
            print("=" * 50 + "\n")
            
            return full_response, all_tool_calls, elapsed
            
        except requests.RequestException as e:
            print(f"请求异常: {e}")
            return None, [], 0.0
        except (TypeError, ValueError) as e:
            print(f"响应解析异常: {e}")
            return None, [], 0.0
    
    def _merge_tool_call(self, all_tool_calls: List[Dict], chunk_tool_call: Dict):
        """合并流式返回的 tool_call 片段"""
        # 不同 Ollama 版本可能将 index 放在 tool_call 或 function 内。
        chunk_func = chunk_tool_call.get("function", {})
        index = chunk_tool_call.get("index", chunk_func.get("index"))
        
        if index is not None and index < len(all_tool_calls):
            # 合并到已有的 tool_call
            existing = all_tool_calls[index]
            func = existing.get("function", {})
            
            # 合并 name
            if chunk_func.get("name"):
                func["name"] = chunk_func["name"]
            
            # arguments 既可能是流式字符串，也可能是 Ollama 直接返回的 dict。
            arguments = chunk_func.get("arguments")
            if arguments is not None:
                previous = func.get("arguments")
                if isinstance(previous, str) and isinstance(arguments, str):
                    func["arguments"] = previous + arguments
                else:
                    func["arguments"] = arguments
            
            existing["function"] = func
            
            # 合并 id
            if chunk_tool_call.get("id"):
                existing["id"] = chunk_tool_call["id"]
        else:
            # 新增 tool_call
            all_tool_calls.append(json.loads(json.dumps(chunk_tool_call)))
            
    def _send_streaming_follow_up(self, prompt: str, tools: List[Dict],
                       tool_calls: List[Dict], tool_results: List[Dict]) -> Optional[str]:
        """发送流式后续请求，实时输出模型的最终回复"""
        messages = [
            {
                "role": "user",
                "content": prompt
            },
            {
                "role": "assistant",
                "tool_calls": tool_calls
            }
        ]
        
        # 添加工具调用结果
        for i, result in enumerate(tool_results):
            messages.append({
                "role": "tool",
                "content": json.dumps(result, ensure_ascii=False),
                "tool_call_id": tool_calls[i].get("id", str(i))
            })
            
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": get_tool_schema_list(),
            "stream": True  # 启用流式输出
        }
        
        try:
            response = self.session.post(
                f"{self.api_url}/api/chat",
                json=payload,
                timeout=180,
                stream=True  # 流式接收
            )
            
            if response.status_code != 200:
                return None
            
            # 收集流式响应并实时输出
            full_content = ""
            
            # 打印模型最终回复的边框
            print("\n" + "💬 " + "=" * 48)
            print("   模型最终回复 (流式输出):")
            print("┌" + "─" * 48 + "┐")
            
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                content = chunk.get("message", {}).get("content", "")
                if content:
                    full_content += content
                    # 使用蓝色高亮最终回复
                    print(f"\033[94m   {content}\033[0m", end="", flush=True)
            
            # 打印结束边框
            print()
            print("└" + "─" * 48 + "┘")
            print("=" * 50)
            
            return full_content
            
        except requests.RequestException as e:
            print(f"后续请求异常: {e}")
        except (TypeError, ValueError) as e:
            print(f"后续响应解析异常: {e}")
            
        return None
        
    def _execute_tool(self, tool_call: Dict) -> Dict:
        """执行工具调用"""
        try:
            function = tool_call.get("function", {})
            func_name = function.get("name")
            arguments = function.get("arguments", {})
            
            # 如果 arguments 是字符串，则解析；否则直接使用
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(arguments, dict):
                return {"status": "error", "message": "工具参数必须是 JSON 对象"}
            
            print(f"\n   调用工具: {func_name}")
            print(f"   参数: {json.dumps(arguments, ensure_ascii=False)}")
            
            result = execute_tool(func_name, arguments)
            
            print(f"   结果: {json.dumps(result, ensure_ascii=False)[:200]}")
            return result
            
        except Exception as e:
            import traceback
            error_detail = f"{type(e).__name__}: {str(e)}"
            print(f"   异常: {error_detail}")
            print(f"   详情: {traceback.format_exc()}")
            return {
                "status": "error",
                "message": error_detail
            }
            
    def run_test_suite(self, test_cases: List[Dict], max_rounds: int = 5) -> Dict:
        """
        运行测试套件
        
        Args:
            test_cases: 测试用例列表
            
        Returns:
            测试结果汇总
        """
        print("\n" + "="*60)
        print("开始 Function Calling 测试")
        print("="*60)
        
        results = []
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n\n{'#'*60}")
            print(f"测试 {i}/{len(test_cases)}: {test_case['name']}")
            print(f"{'#'*60}")
            
            test_start = time.time()
            result = self.test_function_calling(
                prompt=test_case["prompt"],
                tools=test_case.get("tools"),
                max_rounds=max_rounds,
                model_options=test_case.get("options"),
            )
            test_elapsed = time.time() - test_start
            
            self.test_case_times.append({
                "test_name": test_case["name"],
                "elapsed": round(test_elapsed, 2)
            })
            
            results.append({
                "test_name": test_case["name"],
                "result": result
            })
            
        # 打印汇总
        print("\n\n" + "="*60)
        print("测试汇总")
        print("="*60)
        print(f"总测试数: {len(test_cases)}")
        print(f"工具调用总数: {self.call_count}")
        print(f"成功调用数: {self.success_count}")
        print(f"失败调用数: {self.failed_count}")
        
        if self.call_count > 0:
            success_rate = self.success_count / self.call_count * 100
            print(f"成功率: {success_rate:.1f}%")
        
        # 打印耗时汇总
        print(f"\n📊 各测试用例耗时:")
        total_time = 0
        for t in self.test_case_times:
            print(f"  {t['test_name']}: {t['elapsed']:.2f} 秒")
            total_time += t['elapsed']
        print(f"  ─────────────────────")
        print(f"  总耗时: {total_time:.2f} 秒")
            
        # 保存统计信息
        execute_tool(
            "save_data_to_log",
            {
                "category": "test_summary",
                "data": {
                "total_tests": len(test_cases),
                "total_tool_calls": self.call_count,
                "success_calls": self.success_count,
                "failed_calls": self.failed_count,
                "timing": {
                    "test_cases": self.test_case_times,
                    "total_elapsed": round(total_time, 2)
                }
                },
                "priority": "high",
            },
        )
        
        return {
            "test_results": results,
            "summary": {
                "total_tests": len(test_cases),
                "total_tool_calls": self.call_count,
                "success_calls": self.success_count,
                "failed_calls": self.failed_count,
                "timing": {
                    "test_cases": self.test_case_times,
                    "total_elapsed": round(total_time, 2)
                }
            }
        }


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Function Calling 测试工具")
    parser.add_argument("--prompt", "-p", type=str, help="自定义测试提示词")
    parser.add_argument("--config", "-c", type=str, default="config/config.json",
                       help="配置文件路径")
    parser.add_argument("--max-rounds", type=int, default=5,
                       help="单个测试允许的最大工具调用轮数（默认：5）")
    
    args = parser.parse_args()
    
    # 加载配置
    config = {}
    try:
        with open(args.config, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"\n❌ 无法读取配置文件 {args.config}: {e}")
        return
        
    # 自动查找未禁用的模型配置
    models_config = config.get("models", {})
    model_config = None
    
    for model_name, cfg in models_config.items():
        if not cfg.get("disable", False):
            model_config = cfg
            break
    
    if model_config is None:
        print("\n⚠️  所有模型已禁用，请在 config/config.json 中至少启用一个")
        return
        
    api_url = model_config.get("api_url", "http://100.64.0.13:11438")
    model = model_config.get("default_model", "qwen3.6:27b")
    
    # 创建测试器
    tester = FunctionCallingTester(api_url, model)
    
    # 自定义 prompt 只运行一条临时用例；否则完全使用配置文件定义的用例。
    if args.prompt:
        test_cases = [{
            "name": "自定义测试",
            "prompt": args.prompt
        }]
    else:
        configured_cases = config.get("test_cases", {}).get("basic_tests", [])
        if not isinstance(configured_cases, list) or not configured_cases:
            print("\n⚠️  config.json 中未定义 test_cases.basic_tests")
            return

        test_cases = []
        for index, case in enumerate(configured_cases, start=1):
            name = case.get("test_case", f"配置测试 {index}")
            prompt = case.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                print(f"\n⚠️  跳过无效测试用例: {name}（缺少 prompt）")
                continue

            params = case.get("params", {})
            if not isinstance(params, dict):
                print(f"\n⚠️  跳过无效测试用例: {name}（params 必须是对象）")
                continue

            options = {}
            if "temperature" in params:
                options["temperature"] = params["temperature"]
            if "max_tokens" in params:
                options["num_predict"] = params["max_tokens"]

            test_cases.append({"name": name, "prompt": prompt, "options": options})

        if not test_cases:
            print("\n⚠️  没有可执行的配置测试用例")
            return
        
    # 运行测试
    if args.max_rounds < 1:
        parser.error("--max-rounds 必须大于 0")

    tester.run_test_suite(test_cases, max_rounds=args.max_rounds)
    return 0


if __name__ == "__main__":
    exit(main() or 0)
