"""Wire and worker regression evidence for the approved model terminal batch.

Fixtures map the locked GA/WK failure branches to real adapters; no model service
is contacted. Integration assertions verify platform terminal and tool side effects.
"""
import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime
import json

import httpx
import pytest
from sqlalchemy import select

from nexus_core.native import NativePolicy
from nexus_core.runtime import ModelChunk, ModelMessage, ModelRequest, RuntimeFault, ToolCall
from nexus_runtimes.native.models.errors import ModelFault, retry_after, ERROR_BODY_LIMIT
from nexus_runtimes.native.models.openai_compatible import OpenAICompatibleModel
from nexus_runtimes.native.models.protocols.structured import StructuredModel
from nexus_runtimes.native.models.retry import RetryModel
from nexus_runtimes.native.models.routing import RoutedModel
from nexus_runtimes.native.models.tool_protocol import TextToolModel
from nexus_runtimes.native.models.usage import usage_chunk
from test_native_runtime import database, stack, run_row, registry, run_once, ToolResult, ToolInvocationRecord

REQUEST = ModelRequest((ModelMessage('user', 'Hello'),), (), 1000)
PROTOCOLS = ('openai_chat_completions', 'openai_responses', 'anthropic_messages')


def model_for(protocol, handler, *, streaming=True):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    options = {'stream': streaming}
    if protocol == 'openai_chat_completions':
        return OpenAICompatibleModel(model='fake', api_key='secret-marker', http_client=client, options=options)
    return StructuredModel(model='fake', api_key='secret-marker', base_url='https://model.example/v1',
                           protocol=protocol, http_client=client, options=options)


def wire(events):
    return ''.join('data: ' + (json.dumps(e) if isinstance(e, dict) else e) + '\n\n' for e in events)


def chat(delta=None, reason=None, usage=None):
    return {'id': 'fake', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'fake',
            'choices': [{'index': 0, 'delta': delta or {}, 'finish_reason': reason}], **({'usage': usage} if usage else {})}


def fixtures(protocol, reason='normal', calls=False):
    call = {'id': 'call_a', 'type': 'function', 'function': {'name': 'echo', 'arguments': '{"text":"ok"}'}}
    if protocol == 'openai_chat_completions':
        finish = {'normal': 'tool_calls' if calls else 'stop', 'length': 'length', 'filter': 'content_filter'}[reason]
        message = {'role': 'assistant', 'content': 'OK', **({'tool_calls': [call]} if calls else {})}
        data = {'id': 'fake', 'object': 'chat.completion', 'created': 1, 'model': 'fake',
                'choices': [{'index': 0, 'message': message, 'finish_reason': finish}]}
        delta = {'content': 'OK', **({'tool_calls': [{**call, 'index': 7}]} if calls else {})}
        return data, [chat(delta, finish)]
    if protocol == 'openai_responses':
        status = 'completed' if reason == 'normal' else 'incomplete'
        details = {} if status == 'completed' else {'incomplete_details': {'reason': 'content_filter' if reason == 'filter' else 'max_output_tokens'}}
        item = {'type': 'function_call', 'id': 'item_a', 'call_id': 'call_a', 'name': 'echo', 'arguments': '{"text":"ok"}'}
        data = {'status': status, 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'OK'}]}] + ([item] if calls else []), **details}
        events = [{'type': 'response.output_text.delta', 'delta': 'OK'}]
        if calls:
            events.append({'type': 'response.output_item.done', 'output_index': 7, 'item': item})
        return data, events + [{'type': 'response.' + status, 'response': {'status': status, **details}}]
    finish = {'normal': 'tool_use' if calls else 'end_turn', 'length': 'max_tokens', 'filter': 'refusal'}[reason]
    blocks = [{'type': 'text', 'text': 'OK'}] + ([{'type': 'tool_use', 'id': 'call_a', 'name': 'echo', 'input': {'text': 'ok'}}] if calls else [])
    events = [{'type': 'content_block_start', 'index': 0, 'content_block': blocks[0]}, {'type': 'content_block_stop', 'index': 0}]
    if calls:
        events += [{'type': 'content_block_start', 'index': 7, 'content_block': blocks[1]}, {'type': 'content_block_stop', 'index': 7}]
    return {'content': blocks, 'stop_reason': finish}, events + [{'type': 'message_delta', 'delta': {'stop_reason': finish}}, {'type': 'message_stop'}]


@pytest.mark.parametrize('protocol', PROTOCOLS)
@pytest.mark.parametrize('streaming', [True, False])
@pytest.mark.parametrize('reason', ['normal', 'length', 'filter'])
@pytest.mark.parametrize('calls', [True, False])
def test_protocol_outcome_matrix(protocol, streaming, reason, calls):
    async def scenario():
        data, events = fixtures(protocol, reason, calls)
        model = model_for(protocol, lambda _: httpx.Response(200, text=wire(events)) if streaming else httpx.Response(200, json=data), streaming=streaming)
        try:
            chunks = [c async for c in model.stream(REQUEST)]
            assert ''.join(c.text for c in chunks if c.kind == 'text') == 'OK'
            expected = {'normal': 'tool_calls' if calls else 'stop', 'length': 'length', 'filter': 'content_filter'}[reason]
            assert [c.finish_reason for c in chunks if c.kind == 'done'] == [expected]
            assert len([c for c in chunks if c.kind == 'tool_call']) == (int(calls) if reason != 'filter' else 0)
        finally:
            await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('status', ['failed', 'queued', 'in_progress', 'cancelled', 'unknown', None])
@pytest.mark.parametrize('with_output', [True, False])
def test_responses_nonstream_failure_status(status, with_output):
    async def scenario():
        data = {'status': status, 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'not final'}]}] if with_output else []}
        model = model_for('openai_responses', lambda _: httpx.Response(200, json=data), streaming=False)
        seen = []
        try:
            with pytest.raises(RuntimeFault) as fault:
                async for chunk in model.stream(REQUEST): seen.append(chunk)
            assert fault.value.code == ('model_response_failed' if status == 'failed' else 'model_stream_invalid')
            assert not seen
        finally: await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('protocol', PROTOCOLS)
@pytest.mark.parametrize('streaming', [True,False])
@pytest.mark.parametrize('status,code', [(400,'model_request_rejected'),(401,'model_authentication_failed'),(403,'model_authentication_failed'),
    (404,'model_request_rejected'),(408,'model_provider_unavailable'),(409,'model_request_rejected'),(422,'model_request_rejected'),
    (429,'model_rate_limited'),(500,'model_provider_unavailable'),(502,'model_provider_unavailable'),(503,'model_provider_unavailable'),(504,'model_provider_unavailable')])
def test_http_error_classification_and_attempts(protocol, streaming, status, code):
    async def scenario():
        count = 0
        def handler(_):
            nonlocal count
            count += 1
            return httpx.Response(status, json={'error': {'message': 'secret-marker'}})
        model = RetryModel(model_for(protocol, handler, streaming=streaming), NativePolicy(model_retries=1, retry_delay_seconds=0))
        try:
            with pytest.raises(RuntimeFault) as fault: _ = [c async for c in model.stream(REQUEST)]
            assert fault.value.code == code and str(fault.value) == code
            assert 'secret-marker' not in str(fault.value)
            assert count == (2 if status in (408,429,500,502,503,504) else 1)
        finally: await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('protocol', PROTOCOLS)
@pytest.mark.parametrize('status,structured,expected', [(429,'insufficient_quota','model_quota_exhausted'),(400,'context_length_exceeded','model_context_exceeded')])
def test_structured_errors_override_http(protocol, status, structured, expected):
    async def scenario():
        count = 0
        def handler(_):
            nonlocal count
            count += 1
            return httpx.Response(status,json={'error':{'code':structured,'message':'secret-marker'}})
        model = RetryModel(model_for(protocol, handler),NativePolicy(retry_delay_seconds=0))
        try:
            with pytest.raises(RuntimeFault) as fault: _ = [c async for c in model.stream(REQUEST)]
            assert fault.value.code == expected and count == 1
        finally: await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('protocol', PROTOCOLS)
@pytest.mark.parametrize('tail', ['eof', 'done', 'bad_json'])
def test_missing_terminal_or_corrupt_frame_fails_after_partial_text(protocol, tail):
    async def scenario():
        _, events = fixtures(protocol)
        events = events[:1]
        if protocol == 'openai_chat_completions':
            events[0]['choices'][0]['finish_reason'] = None
        events += ['[DONE]'] if tail == 'done' else ['<html>secret-marker</html>'] if tail == 'bad_json' else []
        seen, count = [], 0
        def handler(_):
            nonlocal count
            count += 1
            return httpx.Response(200,text=wire(events))
        model = RetryModel(model_for(protocol,handler),NativePolicy(retry_delay_seconds=0))
        try:
            with pytest.raises(RuntimeFault) as fault:
                async for c in model.stream(REQUEST):seen.append(c)
            assert fault.value.code == 'model_stream_invalid' and count == 1
            assert any(c.text == 'OK' for c in seen) and not any(c.kind in ('done','tool_call') for c in seen)
        finally:await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('closed', [True, False])
@pytest.mark.parametrize('initial', [{}, {'text':'initial'}])
def test_anthropic_closed_and_initial_tool_input(closed, initial):
    async def scenario():
        events = [{'type':'content_block_start','index':7,'content_block':{'type':'tool_use','id':'a','name':'echo','input':initial}}]
        if closed:events += [{'type':'content_block_stop','index':7}]
        events += [{'type':'message_delta','delta':{'stop_reason':'tool_use'}},{'type':'message_stop'}]
        model = model_for('anthropic_messages',lambda _:httpx.Response(200,text=wire(events)))
        try:
            if not closed:
                with pytest.raises(RuntimeFault):_=[c async for c in model.stream(REQUEST)]
            else:
                chunks=[c async for c in model.stream(REQUEST)]
                assert json.loads(chunks[0].tool_call.arguments) == initial
                assert chunks[-1].finish_reason == 'tool_calls'
        finally:await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('with_ids', [True,False])
@pytest.mark.parametrize('done_only', [True,False])
def test_responses_interleaved_parameters_and_sparse_indexes(with_ids, done_only):
    async def scenario():
        events=[]
        for i in (7,2):
            item={'type':'function_call','call_id':f'call{i}','name':'echo','arguments':''}
            if with_ids:item['id']=f'item{i}'
            events.append({'type':'response.output_item.added','output_index':i,'item':item})
        for i in (2,7):
            event={'output_index':i,**({'item_id':f'item{i}'} if with_ids else {})}
            args=json.dumps({'n':i})
            if not done_only:events.append({**event,'type':'response.function_call_arguments.delta','delta':args})
            events.append({**event,'type':'response.function_call_arguments.done','arguments':args})
        events.append({'type':'response.completed','response':{'status':'completed'}})
        model=model_for('openai_responses',lambda _:httpx.Response(200,text=wire(events)))
        try:
            chunks=[c async for c in model.stream(REQUEST)]
            assert {c.tool_call.id:json.loads(c.tool_call.arguments) for c in chunks if c.tool_call} == {'call7':{'n':7},'call2':{'n':2}}
        finally:await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('protocol,value,total', [
    ('openai_responses',{'input_tokens':100,'output_tokens':20,'input_tokens_details':{'cached_tokens':40}},120),
    ('openai_chat_completions',{'prompt_tokens':100,'completion_tokens':20,'prompt_tokens_details':{'cached_tokens':40}},120),
    ('anthropic_messages',{'input_tokens':100,'output_tokens':55,'cache_read_input_tokens':40,'cache_creation_input_tokens':10},205),
    ('openai_responses',{'input_tokens':None,'output_tokens':0,'total_tokens':0},0)])
def test_usage_protocol_totals(protocol,value,total):
    assert usage_chunk(value,protocol).total_tokens==total


@pytest.mark.parametrize('bad', [-1,True,1.5,'1',2**53,{},[]])
def test_usage_rejects_invalid_counts(bad):
    with pytest.raises(RuntimeFault):usage_chunk({'input_tokens':bad})


def test_anthropic_cumulative_usage_keeps_cache_and_input():
    async def scenario():
        _, events=fixtures('anthropic_messages')
        events.insert(0,{'type':'message_start','message':{'usage':{'input_tokens':100,'cache_read_input_tokens':40,'cache_creation_input_tokens':10}}})
        events[-2]['usage']={'output_tokens':55}
        events.insert(-1,events[-2])
        model=model_for('anthropic_messages',lambda _:httpx.Response(200,text=wire(events)))
        try:
            chunks=[c async for c in model.stream(REQUEST)]
            assert [c.total_tokens for c in chunks if c.kind=='usage']==[205]
        finally:await model.close()
    asyncio.run(scenario())


def test_retry_after_formats_bounds_and_cancellation():
    assert retry_after('12')==12
    assert retry_after(format_datetime(datetime(2026,1,1,tzinfo=timezone.utc)),now=datetime(2026,1,1,tzinfo=timezone.utc).timestamp()-30)==30
    for invalid in ('bad','-1','NaN','inf','0'):
        assert retry_after(invalid) is None
    async def scenario():
        counts=[0,0]
        class Bad:
            async def stream(self,request):
                counts[0]+=1
                raise ModelFault('model_rate_limited',retry_after=100)
                yield
            async def close(self):pass
        class Good:
            async def stream(self,request):
                counts[1]+=1
                yield ModelChunk('done',finish_reason='stop')
            async def close(self):pass
        model=RetryModel(RoutedModel([Bad,Good],max_retry_delay_seconds=1),NativePolicy(max_retry_delay_seconds=1))
        with pytest.raises(RuntimeFault) as fault:_=[c async for c in model.stream(REQUEST)]
        assert fault.value.recovery_blocked and counts==[1,0]
        counts[:]=[0,0]
        class Waiting(Bad):
            async def stream(self,request):
                counts[0]+=1
                raise ModelFault('model_rate_limited',retry_after=30)
                yield
        model=RetryModel(Waiting(),NativePolicy(max_retry_delay_seconds=60))
        async def consume():return [c async for c in model.stream(REQUEST)]
        task=asyncio.create_task(consume())
        await asyncio.sleep(.01);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert counts==[1,0]
    asyncio.run(scenario())


def test_buffered_text_failure_cannot_trigger_outer_recovery():
    async def scenario():
        counts=[0,0]
        class Partial:
            async def stream(self,request):
                counts[0]+=1
                yield ModelChunk('text',text='partial')
                raise ModelFault('model_provider_unavailable')
            async def close(self):pass
        class Good:
            async def stream(self,request):
                counts[1]+=1
                yield ModelChunk('done',finish_reason='stop')
            async def close(self):pass
        model=RetryModel(RoutedModel([lambda:TextToolModel(Partial()),Good]),NativePolicy(retry_delay_seconds=0))
        seen=[]
        with pytest.raises(RuntimeFault) as fault:
            async for c in model.stream(REQUEST):seen.append(c)
        assert counts==[1,0] and fault.value.output_started
        assert [c.text for c in seen]==['partial']
    asyncio.run(scenario())


@pytest.mark.parametrize('protocol', PROTOCOLS)
@pytest.mark.parametrize('case', ['failed','filter','open_tool','length'])
def test_worker_does_not_complete_failures_or_execute_unsafe_calls(database,protocol,case):
    if case in ('failed','open_tool') and protocol=='openai_chat_completions':
        case='filter'
    _, _, _, run, _=stack(database,['echo'])
    count=[]
    def echo(args,context):count.append(args);return ToolResult('ok')
    if case=='failed':
        data={'status':'failed','error':{'message':'secret-marker'},'output':[]}
        handler=lambda _:httpx.Response(200,json=data)
        streaming=False
    else:
        _,events=fixtures(protocol,'length' if case=='length' else 'filter',calls=True)
        if case=='open_tool' and protocol=='anthropic_messages':
            events=[e for e in events if not(e.get('type')=='content_block_stop' and e.get('index')==7)]
        elif case=='open_tool':
            events=events[:-1]
        handler=lambda _:httpx.Response(200,text=wire(events))
        streaming=True
    run_once(database,'worker',model_factory=lambda _:model_for(protocol,handler,streaming=streaming),registry_factory=lambda _:registry(echo))
    assert run_row(database,run.id).status=='failed'
    assert count==[]
    with database() as db:
        assert not db.scalars(select(ToolInvocationRecord).where(ToolInvocationRecord.run_id==run.id)).all()


@pytest.mark.parametrize('protocol', PROTOCOLS)
def test_error_bodies_are_bounded_and_closed(protocol):
    class Body(httpx.AsyncByteStream):
        def __init__(self):self.parts=0;self.closed=False
        async def __aiter__(self):
            for _ in range(100):
                self.parts+=1
                yield b'x'*8192
        async def aclose(self):self.closed=True
    async def scenario():
        body=Body()
        model=model_for(protocol,lambda _:httpx.Response(401,stream=body))
        try:
            with pytest.raises(RuntimeFault) as fault:_=[c async for c in model.stream(REQUEST)]
            assert fault.value.code=='model_authentication_failed'
            assert body.parts <= ERROR_BODY_LIMIT//8192+1 and body.closed
        finally:await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('protocol', PROTOCOLS)
def test_transport_failure_after_text_closes_without_retry(protocol):
    class Body(httpx.AsyncByteStream):
        def __init__(self):self.closed=False
        async def __aiter__(self):
            _,events=fixtures(protocol)
            if protocol=='openai_chat_completions':events[0]['choices'][0]['finish_reason']=None
            yield wire(events[:1]).encode()
            raise httpx.ReadError('secret-marker')
        async def aclose(self):self.closed=True
    async def scenario():
        count=0;body=Body();seen=[]
        def handler(_):
            nonlocal count
            count+=1
            return httpx.Response(200,stream=body)
        model=RetryModel(model_for(protocol,handler),NativePolicy(retry_delay_seconds=0))
        try:
            with pytest.raises(RuntimeFault) as fault:
                async for c in model.stream(REQUEST):seen.append(c)
            assert count==1 and body.closed
            assert any(c.text=='OK' for c in seen)
            assert fault.value.code in ('model_provider_unavailable','model_stream_invalid')
            assert str(fault.value)==fault.value.code
        finally:await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('protocol', PROTOCOLS)
def test_http_retry_after_waits_before_next_request(protocol,monkeypatch):
    from nexus_runtimes.native.models import retry
    waits=[]
    async def sleep(delay):waits.append(delay)
    monkeypatch.setattr(retry.asyncio,'sleep',sleep)
    async def scenario():
        count=0
        _,events=fixtures(protocol)
        def handler(_):
            nonlocal count
            count+=1
            if count==1:return httpx.Response(429,headers={'retry-after':'2'},json={'error':{'message':'wait'}})
            assert waits==[2]
            return httpx.Response(200,text=wire(events))
        model=RetryModel(model_for(protocol,handler),NativePolicy(retry_delay_seconds=0,max_retry_delay_seconds=3))
        try:
            chunks=[c async for c in model.stream(REQUEST)]
            assert count==2 and chunks[-1].finish_reason=='stop'
        finally:await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('protocol', PROTOCOLS)
def test_network_failure_before_output_can_retry(protocol):
    async def scenario():
        count=0
        _,events=fixtures(protocol)
        def handler(request):
            nonlocal count
            count+=1
            if count==1:raise httpx.ConnectError('secret-marker',request=request)
            return httpx.Response(200,text=wire(events))
        model=RetryModel(model_for(protocol,handler),NativePolicy(retry_delay_seconds=0))
        try:
            chunks=[c async for c in model.stream(REQUEST)]
            assert count==2 and chunks[-1].finish_reason=='stop'
        finally:await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('protocol', PROTOCOLS)
def test_explicit_200_error_never_succeeds(protocol):
    async def scenario():
        model=model_for(protocol,lambda _:httpx.Response(200,json={'error':{'message':'secret-marker'},'choices':[]}),streaming=False)
        try:
            with pytest.raises(RuntimeFault) as fault:_=[c async for c in model.stream(REQUEST)]
            assert fault.value.code=='model_response_failed'
        finally:await model.close()
    asyncio.run(scenario())


def test_worker_event_replay_and_repeated_delivery_do_not_request_again(database):
    from nexus_platform.runs.service import list_events
    principal,tenant,_,run,_=stack(database)
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={'status':'failed','output':[]})
    factory=lambda _:model_for('openai_responses',handler,streaming=False)
    run_once(database,'worker',model_factory=factory)
    assert run_row(database,run.id).error_code=='model_response_failed'
    with database() as db:
        events=list_events(db,principal,tenant.id,run.id,after_sequence=0)
        assert events
    run_once(database,'worker',model_factory=factory)
    assert len(requests)==1


@pytest.mark.parametrize('reason', ['length','content_filter'])
def test_text_protocol_cannot_turn_filtered_or_truncated_tags_into_tools(reason):
    async def scenario():
        class Text:
            async def stream(self,request):
                yield ModelChunk('text',text='<tool_use>{"name":"echo","arguments":{}}</tool_use>')
                yield ModelChunk('done',finish_reason=reason)
            async def close(self):pass
        chunks=[c async for c in TextToolModel(Text()).stream(REQUEST)]
        assert chunks[-1].finish_reason==reason and not any(c.tool_call for c in chunks)
    asyncio.run(scenario())


@pytest.mark.parametrize('no_index', [True,False])
def test_chat_multiple_tool_calls_keep_stable_ids_and_sparse_order(no_index):
    async def scenario():
        events=[]
        for index,identity in ((7,'b'),(2,'a')):
            delta={'id':identity,'function':{'name':'echo','arguments':''}}
            if not no_index:delta['index']=index
            events.append(chat({'tool_calls':[delta]}))
            fragment={'id':identity,'function':{'name':'echo','arguments':'{}'}}
            if not no_index:fragment['index']=index
            events.append(chat({'tool_calls':[fragment]}))
        events.append(chat(reason='tool_calls'))
        model=model_for('openai_chat_completions',lambda _:httpx.Response(200,text=wire(events)))
        try:
            chunks=[c async for c in model.stream(REQUEST)]
            calls=[c.tool_call for c in chunks if c.tool_call]
            assert [c.id for c in calls]==(['b','a'] if no_index else ['a','b'])
            assert all(c.name=='echo' and c.arguments=='{}' for c in calls)
        finally:await model.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('protocol', PROTOCOLS)
def test_bad_tools_fail_instead_of_becoming_plain_answer(protocol):
    async def scenario():
        data,_=fixtures(protocol,calls=True)
        if protocol=='openai_chat_completions':data['choices'][0]['message']['tool_calls'][0]['function']['name']=123
        elif protocol=='openai_responses':data['output'][-1]['name']=123
        else:data['content'][-1]['name']=123
        model=model_for(protocol,lambda _:httpx.Response(200,json=data),streaming=False)
        try:
            with pytest.raises(RuntimeFault) as fault:_=[c async for c in model.stream(REQUEST)]
            assert fault.value.code=='model_stream_invalid'
        finally:await model.close()
    asyncio.run(scenario())


def test_cooperative_cancel_during_backoff_closes_and_stops_requests():
    from nexus_runtimes.native.engine.turn import collect_response
    from nexus_runtimes.native.engine.cancellation import CancellationToken
    async def scenario():
        requests=[]
        class Body(httpx.AsyncByteStream):
            def __init__(self):self.closed=False
            async def __aiter__(self):yield b'{}'
            async def aclose(self):self.closed=True
        body=Body()
        def handler(request):
            requests.append(request)
            return httpx.Response(429,headers={'retry-after':'30'},stream=body)
        class Store:
            async def emit(self,*args):pass
        token=CancellationToken()
        model=RetryModel(model_for('openai_responses',handler),NativePolicy())
        task=asyncio.create_task(collect_response(model,REQUEST,token,Store(),1,1))
        while not requests:await asyncio.sleep(0)
        token.cancel()
        try:
            with pytest.raises(RuntimeFault) as fault:await task
            assert fault.value.code=='cancelled' and len(requests)==1 and body.closed
        finally:await model.close()
    asyncio.run(scenario())
