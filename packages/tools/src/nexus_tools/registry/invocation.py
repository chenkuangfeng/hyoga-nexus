"""Adapt GA ordinary/generator handlers to cooperative async execution.

Derived from agent_loop.try_call_generator (a9a36b4, MIT). Blocking synchronous
handlers are limited to trusted registered functions; they run off the event loop and must
observe context.cancellation themselves. Unknown side effects remain interrupted on timeout.
"""
import asyncio
import inspect
from nexus_core.runtime import RuntimeFault, ToolResult


def _advance(generator):
    try:
        return False, next(generator)
    except StopIteration as stopped:
        return True, stopped.value


async def invoke(tool, arguments, context, progress):
    """Preserve yielded progress and a final ToolResult for normal, sync/async generator tools."""
    handler = tool.handler
    value = handler(arguments, context) if inspect.iscoroutinefunction(handler) or inspect.isasyncgenfunction(handler) else await asyncio.to_thread(handler, arguments, context)
    if inspect.isawaitable(value):
        return await value
    if inspect.isasyncgen(value):
        final = None
        try:
            async for item in value:
                context.cancellation.check()
                if isinstance(item, ToolResult):
                    if final is not None:
                        raise RuntimeFault('tool_result_invalid')
                    final = item
                else:
                    if final is not None:
                        raise RuntimeFault('tool_result_invalid')
                    await progress(str(tool.public_result(ToolResult(str(item))))[:4000])
        finally:
            await value.aclose()
        if final is None:
            raise RuntimeFault('tool_result_invalid')
        return final
    if inspect.isgenerator(value):
        try:
            while True:
                context.cancellation.check()
                ended, item = await asyncio.to_thread(_advance, value)
                if ended:
                    return item
                await progress(str(tool.public_result(ToolResult(str(item))))[:4000])
        finally:
            # A generator still executing in a worker thread cannot be forcibly closed.
            try:
                await asyncio.to_thread(value.close)
            except ValueError:
                pass
    return value
