from langchain.chat_models import init_chat_model

LLM = init_chat_model(
    "global.anthropic.claude-haiku-4-5-20251001-v1:0",
    model_provider="bedrock_converse",
    region_name="sa-east-1",
)
