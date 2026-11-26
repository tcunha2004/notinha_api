from langgraph.graph import END, START, StateGraph

from agent.extraction.nodes.extract.node import node_extract_data
from agent.extraction.nodes.save.node import node_save
from agent.extraction.nodes.store_logo.node import node_store_logo
from agent.extraction.state import GraphState


class Graph:
    def __init__(self):
        builder = StateGraph(GraphState)
        builder.add_node("extract", node_extract_data)
        builder.add_node("store_logo", node_store_logo)
        builder.add_node("save", node_save)
        builder.add_edge(START, "extract")
        builder.add_edge("store_logo", "save")
        builder.add_edge("save", END)
        self.compiler = builder.compile()
