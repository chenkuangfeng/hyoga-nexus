"""Shared provider connection pool: one TCP connection serves many Runs, credentials stay per call,
and a pool is never used from another event loop."""
import asyncio

import pytest

from nexus_core.runtime import RuntimeFault
from nexus_runtimes.native.models import network

RESPONSE = b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}'


async def _serve(accepted):
    async def handle(reader, writer):
        accepted.append(1)
        try:
            while True:
                await reader.readuntil(b'\r\n\r\n')
                writer.write(RESPONSE)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
    server = await asyncio.start_server(handle, '127.0.0.1', 0)
    return server, server.sockets[0].getsockname()[1]


@pytest.fixture()
def allow_loopback(monkeypatch):
    monkeypatch.setenv('NEXUS_MODEL_PRIVATE_HOST_ALLOWLIST', '127.0.0.1')


def _run_sequential_runs(port, *, share, runs=3):
    async def main():
        accepted = []
        server, port_ = await _serve(accepted)
        try:
            for _ in range(runs):
                # Each Run builds its own client, as the worker does, and closes it at the end.
                client = network.provider_client(f'http://127.0.0.1:{port_}/v1', share_connections=share)
                response = await client.get(f'http://127.0.0.1:{port_}/v1/models')
                assert response.status_code == 200
                await client.aclose()
            return len(accepted)
        finally:
            server.close()
            await server.wait_closed()
    return asyncio.run(main())


def test_without_sharing_each_run_opens_its_own_connection(allow_loopback):
    assert _run_sequential_runs(0, share=False) == 3


def test_shared_pool_reuses_one_connection_across_runs(allow_loopback):
    assert _run_sequential_runs(0, share=True) == 1


def test_closing_a_run_client_does_not_close_the_shared_pool(allow_loopback):
    async def main():
        accepted = []
        server, port = await _serve(accepted)
        try:
            first = network.provider_client(f'http://127.0.0.1:{port}/v1', share_connections=True)
            await first.get(f'http://127.0.0.1:{port}/v1/models')
            await first.aclose()
            second = network.provider_client(f'http://127.0.0.1:{port}/v1', share_connections=True)
            assert (await second.get(f'http://127.0.0.1:{port}/v1/models')).status_code == 200
            await second.aclose()
            return len(accepted)
        finally:
            server.close()
            await server.wait_closed()
    assert asyncio.run(main()) == 1


def test_pool_is_not_handed_to_another_event_loop(allow_loopback):
    url = 'http://127.0.0.1:9/v1'
    async def owner():
        return network.shared_connection_pool(url)
    async def stranger():
        return network.shared_connection_pool(url)
    pool = asyncio.run(owner())
    assert pool is not None
    assert asyncio.run(stranger()) is None


def test_no_pool_outside_a_running_loop(allow_loopback):
    assert network.shared_connection_pool('http://127.0.0.1:10/v1') is None


def test_shared_pool_still_refuses_disallowed_destinations(allow_loopback, monkeypatch):
    monkeypatch.setenv('NEXUS_MODEL_PRIVATE_HOST_ALLOWLIST', '')
    async def main():
        # Validation happens when the client is built, before any connection is looked up in the pool.
        with pytest.raises(RuntimeFault) as caught:
            network.provider_client('http://127.0.0.1:11/v1', share_connections=True)
        assert caught.value.code == 'model_destination_denied'
    asyncio.run(main())
