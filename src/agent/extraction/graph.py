from langgraph.graph import END, START, StateGraph

from agent.extraction.nodes.extract.node import node_extract_data
from agent.extraction.state import GraphState


class Graph:
    def __init__(self):
        builder = StateGraph(GraphState)
        builder.add_node("extract", node_extract_data)
        # builder.add_node("validate", "")
        # builder.add_node("save", "")
        builder.add_edge(START, "extract")
        # builder.add_edge("extract", "validate")
        # builder.add_conditional_edges("validate", "", ["save", "extract", END])
        # builder.add_edge("save", END)
        builder.add_edge("extract", END)
        self.compiler = builder.compile()
