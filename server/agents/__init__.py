import os

from .base import Agent, AgentError, AgentRegistry, clear_cache, mem_info
from .code_specialist import CodeSpecialistAgent
from .embedding import EmbeddingAgent, MemoryStore
from .orchestrator import Cancelled, ResearchPipeline, decide, format_for_main
from .reranker import RerankerAgent
from .researcher import ResearcherAgent
from .tools import DocFetcher, make_search_tool


def build_system(model_manager=None):
    registry = AgentRegistry(
        [ResearcherAgent(), RerankerAgent(), EmbeddingAgent(), CodeSpecialistAgent()],
        max_resident=1,
        model_manager=model_manager,
    )
    memory = MemoryStore(os.getenv("SXARF_MEMORY_PATH", "~/.sxarf/memory.json"))
    search = make_search_tool(os.getenv("SXARF_SEARCH", "ddg"))
    pipeline = ResearchPipeline(registry, search, DocFetcher(), memory)
    return registry, pipeline, memory
