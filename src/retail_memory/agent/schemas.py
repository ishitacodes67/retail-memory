"""Pydantic argument schemas for tools, converted to Groq/OpenAI tool-definition
JSON. One tool only today (get_sales_summary) -- more get added once this works.
"""

from pydantic import BaseModel, Field


class GetSalesSummaryArgs(BaseModel):
    product_id: int = Field(description="The numeric product identifier")
    start_week: int = Field(description="First week of the window (1-102)")
    end_week: int = Field(description="Last week of the window (1-102)")


def to_tool_definition(name: str, description: str, args_model: type[BaseModel]) -> dict:
    schema = args_model.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": schema},
    }


GET_SALES_SUMMARY_TOOL = to_tool_definition(
    "get_sales_summary",
    "Get total units sold, revenue, average price, and number of promo weeks "
    "for a specific product over a range of weeks (1-102).",
    GetSalesSummaryArgs,
)


class RecommendMarkdownArgs(BaseModel):
    product_id: int = Field(description="The numeric product identifier")
    margin: float = Field(
        description="Assumed gross margin as a decimal, e.g. 0.3 for 30%", gt=0, lt=1
    )


RECOMMEND_MARKDOWN_TOOL = to_tool_definition(
    "recommend_markdown",
    "Recommend a discount depth for a product given an assumed profit margin. "
    "Will refuse if the elasticity estimate isn't confident enough, or if demand "
    "is too inelastic for a discount to be profit-optimal.",
    RecommendMarkdownArgs,
)

ALL_TOOLS = [GET_SALES_SUMMARY_TOOL, RECOMMEND_MARKDOWN_TOOL]