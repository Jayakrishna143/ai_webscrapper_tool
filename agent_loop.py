# agent_loop.py
import os
import json
import asyncio
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv
from groq import Groq  # changed

load_dotenv()

MODEL_NAME = "openai/gpt-oss-120b"  # or "mixtral-8x7b-32768"

def get_system_prompt(extraction_goal):
    return f"""
    You are an advanced, self-healing data pipeline architect.
    Your objective is to extract data from a target URL based on the following goal:
    {extraction_goal}

    STRICT RULE: You ARE NOT ALLOWED to provide the final data until you have successfully executed the `run_extraction_code` tool and received a valid JSON response from it.

    You MUST follow these exact steps:
    1. Call the `fetch_html` tool with the target URL.
       - If the site is a modern JS-heavy site (e-commerce, SPAs, React/Angular apps), pass use_selenium=True.
       - If the site is simple and static (blogs, Wikipedia, quotes pages), pass use_selenium=False or omit it.
    2. Analyze the returned HTML to identify CSS classes and tags.
    3. Call the `run_extraction_code` tool with the exact Python script required.
       - Your code runs where `html_content` and `BeautifulSoup` are already available.
       - You MUST assign your final list of dictionaries to `extracted_data`.
       - Do NOT wrap your code in python markdown blocks; supply the raw string payload.
    4. SELF-HEALING: If `run_extraction_code` returns an error, read it, rewrite your code, and call it again.
    5. Once you receive the successful JSON string back from the tool, output the final JSON data and STOP calling tools.
    """

def translate_mcp_tools_to_groq(mcp_tools) -> list[dict]:
    tools = []
    for tool in mcp_tools:
        tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema,
            }
        })
    return tools

async def run_agent(target_url: str, extraction_goal: str, log_callback=print):
    groq_client = Groq()  # reads GROQ_API_KEY from env automatically

    server_params = StdioServerParameters(command="python", args=["mcp_server.py"], env=None)

    async with AsyncExitStack() as stack:
        log_callback("Initializing standard input/output transport streams...")
        stdio_transport = await stack.enter_async_context(stdio_client(server_params))
        read_stream, write_stream = stdio_transport

        log_callback("Establishing Model Context Protocol session...")
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()

        mcp_tools_response = await session.list_tools()
        groq_tools = translate_mcp_tools_to_groq(mcp_tools_response.tools)  # changed

        # messages are already in OpenAI format, no conversion needed
        messages = [
            {"role": "system", "content": get_system_prompt(extraction_goal)},  # system goes here now
            {"role": "user", "content": f"Begin. Target URL: {target_url}. Goal: {extraction_goal}"}
        ]
        last_executed_code = None

        log_callback(f"\nInitiating ReAct Cognitive Loop against {target_url}\n")

        MAX_ITERATIONS = 5
        iteration_count = 0

        while iteration_count < MAX_ITERATIONS:
            iteration_count += 1
            log_callback(f"--- Iteration {iteration_count} ---")
            log_callback("Dispatching state history to Groq inference engine...")

            # Groq call — no history conversion needed, messages go directly
            response = groq_client.chat.completions.create(
                model=MODEL_NAME,
                messages=messages,
                tools=groq_tools,
                tool_choice="auto",
            )

            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls or []

            # append assistant message to history
            messages.append({
                "role": "assistant",
                "content": response_message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in tool_calls
                ]
            })

            if not tool_calls:
                log_callback("\n=== COGNITIVE LOOP TERMINATED: TARGET STATE REACHED ===\n")
                final_answer = response_message.content or ""
                code_used = last_executed_code if last_executed_code else "No code executed."
                return final_answer, code_used

            for tc in tool_calls:
                tool_name = tc.function.name
                raw_arguments = tc.function.arguments

                log_callback(f"Action Requested: Invoking {tool_name}")

                try:
                    parsed_args = json.loads(raw_arguments)
                    if tool_name == "run_extraction_code":
                        last_executed_code = parsed_args.get("python_code", "")

                    tool_result = await session.call_tool(tool_name, arguments=parsed_args)

                    if tool_result.content and len(tool_result.content) > 0:
                        result_text = tool_result.content[0].text
                    else:
                        result_text = "Execution succeeded, but no data was returned."

                    log_callback(f"Action Succeeded. Returned {len(result_text)} characters.")

                except Exception as e:
                    result_text = f"Tool invocation error: {str(e)}"
                    log_callback(result_text)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text
                })

        if iteration_count >= MAX_ITERATIONS:
            msg = "Maximum loop iterations reached. The system failed to converge."
            log_callback(msg)
            return msg, last_executed_code

if __name__ == "__main__":
    url = "https://quotes.toscrape.com/"
    goal = "Extract exactly 10 quotes..."
    asyncio.run(run_agent(url, goal))