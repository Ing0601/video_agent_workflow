from .base import BaseTool

class ExampleTool(BaseTool):
    def __init__(self):
        super().__init__()
        self.name = "get_weather"
        self.description = "Get the weather of a city"
        self.parameters = {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "The city to get the weather of",
                }
            },
            "required": ["city"],
        }
    
    async def execute(self, **kwargs):
        return {
            "weather": "sunny",
        }

def get_example_tool_schema():
    tool = ExampleTool()
    return tool.get_schema()