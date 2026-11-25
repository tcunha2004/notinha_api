from agent.extraction.nodes.extract.node import node_extract_data
from agent.extraction.nodes.save.node import node_save
from agent.extraction.state import GraphState
from langgraph.graph import END, START, StateGraph


class Graph:
    def __init__(self):
        builder = StateGraph(GraphState)
        builder.add_node("extract", node_extract_data)
        builder.add_node("save", node_save)
        builder.add_edge(START, "extract")
        builder.add_edge("save", END)
        self.compiler = builder.compile()
