# Lets edbot_agent.py use middleware.ConversationMiddleware etc. instead of the full submodule paths
from middleware.conversation_history import ConversationMiddleware, InjectConversationMiddleware
from middleware.validate_input import SUBAGENT_INPUT_SCHEMAS, validate_subagent_input
