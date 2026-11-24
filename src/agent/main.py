from pathlib import Path
from uuid import uuid4

from agent.extraction.graph import Graph
from agent.extraction.state import MediaType

graph = Graph()
result = graph.compiler.invoke(
    input={
        "uuid": uuid4(),
        "media_type": MediaType.JPG,
        "user_id": "001",
        "image": Path("~/Downloads/nf_convertida.jpg").expanduser().read_bytes(),
    }
)
print(result["data"])
