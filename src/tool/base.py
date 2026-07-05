"""
Base class for all tools.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseTool(ABC):
    """Base class for all tools"""

    def __init__(self):
        self.name: str = ""
        self.description: str = ""
        self.parameters: Dict[str, Any] = {}
        self.introduction: str = ""  # 新增字段用于UI展示

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """Execute the tool with given parameters"""
        pass

    def get_schema(self) -> Dict[str, Any]:
        """Get OpenAI-compatible function schema for this tool"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_enhanced_parameters(),
            },
        }

    def validate_params(self, **kwargs) -> Dict[str, Any]:
        """Basic parameter validation (can be overridden by subclasses)"""
        # 获取增强后的参数配置（包含introduction字段）
        enhanced_parameters = self.get_enhanced_parameters()
        required = enhanced_parameters.get("required", [])
        missing = [param for param in required if param not in kwargs]

        if missing:
            return {
                "success": False,
                "error": f"Missing required parameters: {missing}",
            }

        return {"success": True}

    def get_enhanced_parameters(self) -> Dict[str, Any]:
        """Get enhanced parameters with introduction field"""
        enhanced_parameters = self.parameters.copy()
        if "properties" not in enhanced_parameters:
            enhanced_parameters["properties"] = {}

        enhanced_parameters["properties"]["introduction"] = {
            "type": "string",
            "description": "Brief description of the function call intent in user's language, required and concise",
        }

        # 确保introduction在required字段中
        if "required" not in enhanced_parameters:
            enhanced_parameters["required"] = []
        if "introduction" not in enhanced_parameters["required"]:
            enhanced_parameters["required"].append("introduction")

        return enhanced_parameters
