from backend.core.data_store import get_store


class ConversationManager:
    def __init__(self):
        self._current_id: str | None = None

    @property
    def current_id(self) -> str | None:
        return self._current_id

    def new_conversation(self, title: str = "New conversation") -> str:
        store = get_store()
        conv = store.create_conversation(title)
        self._current_id = conv["id"]
        return conv["id"]

    def load_conversation(self, conversation_id: str) -> bool:
        store = get_store()
        conv = store.get_conversation(conversation_id)
        if conv:
            self._current_id = conversation_id
            return True
        return False

    def add_message(self, role: str, content: str, conversation_id: str = None) -> dict | None:
        store = get_store()
        cid = conversation_id or self._current_id
        if not cid:
            cid = self.new_conversation()
        return store.add_message(cid, role, content)

    def get_context(self, limit: int = 20) -> list[dict]:
        store = get_store()
        if not self._current_id:
            return []
        return store.get_recent_messages(self._current_id, limit)

    def list_conversations(self) -> list[dict]:
        store = get_store()
        return store.list_conversations()

    def delete_conversation(self, conversation_id: str) -> bool:
        store = get_store()
        if store.delete_conversation(conversation_id):
            if self._current_id == conversation_id:
                self._current_id = None
            return True
        return False

    def get_title(self) -> str:
        store = get_store()
        if not self._current_id:
            return "No conversation"
        conv = store.get_conversation(self._current_id)
        return conv["title"] if conv else "No conversation"
