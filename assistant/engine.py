import json as json_lib
from datetime import date

import httpx

from assistant.llm_client import LLMClient
from assistant.function_registry import dispatch_call
from assistant.memory.conversation_manager import ConversationManager

SYSTEM_PROMPT = """You are Mayday, an AI personal assistant running on the user's desktop.
You help manage todos, calendar events, and answer questions conversationally.
You have access to tools for creating, updating, deleting, and listing todos and events.
Be concise, helpful, and friendly. When you use a tool, explain what you did.
Current date: {date}"""

CONNECTION_HINT = (
    "Make sure Ollama is running locally (`ollama serve`), "
    "or update config.yaml with your cloud endpoint and API key."
)


class Engine:
    def __init__(self):
        self.llm = LLMClient()
        self.conv = ConversationManager()
        self._on_text = None
        self._on_error = None

    def on_text(self, callback):
        self._on_text = callback

    def on_error(self, callback):
        self._on_error = callback

    def _call_llm(self, messages: list[dict]) -> tuple[str | None, list | None]:
        resp = self.llm.chat(messages, stream=False)
        resp.raise_for_status()
        return self.llm.extract_response(resp)

    def process_message(self, user_text: str):
        try:
            system = SYSTEM_PROMPT.format(date=date.today().isoformat())

            self.conv.add_message("user", user_text)
            messages = [{"role": "system", "content": system}] + self.conv.get_context()

            content, tool_calls = self._call_llm(messages)

            if tool_calls:
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    fn_args = tc["function"]["arguments"]
                    if isinstance(fn_args, str):
                        fn_args = json_lib.loads(fn_args)
                    result = dispatch_call(fn_name, fn_args)
                    self.conv.add_message("assistant", f"[Called {fn_name}] {result}")
                    if self._on_text:
                        self._on_text(f"🔧 **{fn_name}**: {result}")

                messages = [{"role": "system", "content": system}] + self.conv.get_context()
                content, _ = self._call_llm(messages)

            if content:
                self.conv.add_message("assistant", content)
                if self._on_text:
                    self._on_text(content)

        except httpx.ConnectError:
            msg = f"Cannot reach {self.llm.endpoint}. {CONNECTION_HINT}"
            if self._on_error:
                self._on_error(msg)
        except httpx.HTTPStatusError as e:
            msg = f"LLM returned HTTP {e.response.status_code}. Check your model and API key."
            if self._on_error:
                self._on_error(msg)
        except Exception as e:
            if self._on_error:
                self._on_error(str(e))
