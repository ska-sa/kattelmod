import asyncio
import async_solipsism
from unittest import mock

import katsdptelstate.aio

import kattelmod
from kattelmod.component import Component, TelstateUpdatingComponent, KATCPComponent, MultiMethod
from kattelmod.clock import get_clock
from kattelmod.test.test_clock import WarpEventLoopTestCase
import re
import pytest


class DummyComponent(Component):
    def __init__(self, speed: float) -> None:
        super().__init__()
        self._name = 'dummy'
        self._initialise_attributes(locals())
        self._add_dummy_methods('capture_start capture_stop')
        self.temperature = 451.0
        self.pressure = 1000.0


class DummyTelstateUpdatingComponent(TelstateUpdatingComponent):
    def __init__(self, speed: float) -> None:
        super().__init__()
        self._name = 'dummy'
        self._initialise_attributes(locals())
        self.temperature = 451.0
        self.pos_foo = 1000.0     # Will be rate limited by name


class TestComponent(WarpEventLoopTestCase):
    def setup_method(self):
        self.comp = DummyComponent(88.0)

    def test_type(self):
        assert self.comp._type() == 'kattelmod.test.test_component.DummyComponent'

    def test_repr(self):
        assert re.search(r"<kattelmod\.test\.test_component\.DummyComponent 'dummy' at .*>", repr(self.comp))

    def test_sensors(self):
        assert self.comp._sensors == ['pressure', 'speed', 'temperature']

    async def test_dummy_methods(self):
        # Just tests that it exists and runs without crashing
        await self.comp.capture_stop()

    def test_fake(self):
        # Fake up the import so that it just returns this module again, instead
        # of trying to go into kattelmod.systems. Note that this cannot be a
        # decorator because 'kattelmod.test.test_component' is not defined at
        # the time the module is being imported.
        with mock.patch('kattelmod.component.import_module',
                        return_value=kattelmod.test.test_component):
            self.comp.temperature = 100.0
            fake = self.comp._fake()
            assert fake.temperature == 100.0
            assert fake.pressure == 1000.0
            assert fake.speed == 88.0


class TestTelstateUpdatingComponent(WarpEventLoopTestCase):
    # XXX Make it autouse until Pytest supports async setup_methods
    @pytest.fixture(autouse=True)
    async def setup_method(self):
        self.telstate = katsdptelstate.aio.TelescopeState()
        self.comp = DummyTelstateUpdatingComponent(88.0)
        self.comp._name = 'dummy'
        self.comp._telstate = self.telstate
        await self.comp._start()
        # Some of the internal are based around whether there has been an update
        # yet.
        self.comp._update(self.START_TIME)

    async def test_setattr(self):
        """Basic test that setting an attribute updates telstate"""
        await self.comp._flush()
        assert await self.telstate.get('dummy_speed') == 88.0
        assert await self.telstate.key_type('dummy_speed') == \
                         katsdptelstate.KeyType.IMMUTABLE
        # Initial value is pushed into the past
        assert await self.telstate.get_range('dummy_temperature', st=0) == \
                         [(451.0, self.START_TIME - 300.0)]
        get_clock().advance(5)
        self.comp.temperature = 100.0
        await self.comp._flush()
        assert await self.telstate.get_range('dummy_temperature', st=0) == \
                         [(451.0, self.START_TIME - 300.0), (100.0, self.START_TIME + 5.0)]

    async def test_updates(self):
        """Test interaction with _update and rate limiting.

        Normally the attribute setting would be done in the _update callback,
        but it's easier to put them in the test rather than in the dummy
        class.
        """
        for i in range(6):
            get_clock().advance(0.25)
            self.comp._update(get_clock().time())
            self.comp.temperature += 1.0
            self.comp.pos_foo += 1.0
        await self.comp._flush()
        assert await self.telstate.get_range('dummy_temperature', st=0) == \
            [(451.0, self.START_TIME - 300.0),
             (452.0, self.START_TIME + 0.25),
             (453.0, self.START_TIME + 0.5),
             (454.0, self.START_TIME + 0.75),
             (455.0, self.START_TIME + 1.0),
             (456.0, self.START_TIME + 1.25),
             (457.0, self.START_TIME + 1.5)]
        assert await self.telstate.get_range('dummy_pos_foo', st=0) == \
            [(1000.0, self.START_TIME - 300.0),
             (1002.0, self.START_TIME + 0.5),
             (1004.0, self.START_TIME + 1.0),
             (1006.0, self.START_TIME + 1.5)]

    def test_updatable(self):
        assert self.comp._updatable

    async def test_start_twice(self):
        # Mostly just to get test coverage
        await self.comp._start()


def test_bad_katcp_endpoint():
    with pytest.raises(ValueError):
        KATCPComponent('invalid.com')
    with pytest.raises(ValueError):
        KATCPComponent('')


class TestKATCPComponent:
    @classmethod
    @pytest.fixture
    def event_loop(cls):
        loop = async_solipsism.EventLoop()
        yield loop
        loop.close()

    @pytest.fixture(autouse=True)
    async def setup_method(self) -> None:
        loop = asyncio.get_running_loop()
        self.server = await asyncio.start_server(self._client_cb, '127.0.0.1', 0)
        self.endpoint = self.server.sockets[0].getsockname()[:2]
        self.reader = loop.create_future()    # type: asyncio.Future[asyncio.StreamReader]
        self.writer = loop.create_future()    # type: asyncio.Future[asyncio.StreamWriter]
        yield
        writer = await self.writer
        writer.close()
        self.server.close()
        await self.server.wait_closed()

    def _client_cb(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader.set_result(reader)
        self.writer.set_result(writer)

    async def test_connect_timeout(self):
        comp = KATCPComponent('{}:{}'.format(*self.endpoint))
        task = asyncio.ensure_future(comp._start())
        await asyncio.sleep(100)
        with pytest.raises(asyncio.TimeoutError):
            await task

    async def _interact(self):
        reader = await self.reader
        writer = await self.writer
        writer.write(b'#version-connect katcp-protocol 5.0-MI\n')
        await writer.drain()
        await reader.readline()
        writer.write(b'!ping[1] ok hello\n')
        await writer.drain()

    async def test_good(self):
        loop = asyncio.get_running_loop()
        task = loop.create_task(self._interact())
        comp = KATCPComponent('{}:{}'.format(*self.endpoint))
        await comp._start()
        await comp._start()      # Check that it's idempotent
        response = await comp._client.request('ping', 'hello')
        assert response == ([b'hello'], [])
        await comp._stop()
        await comp._stop()       # Check that it's idempotent
        await task


class SyncMethod:
    def __init__(self):
        self.called_with = None

    def my_method(self, *args, **kwargs):
        self.called_with = (args, kwargs)


class AsyncMethod:
    def __init__(self):
        self.called_with = None

    async def my_method(self, *args, **kwargs):
        await asyncio.sleep(0)
        self.called_with = (args, kwargs)


class TestMultiMethod:
    def setup_method(self):
        self.sync1 = SyncMethod()
        self.sync2 = SyncMethod()
        self.async1 = AsyncMethod()
        self.async2 = AsyncMethod()

    def test_sync(self):
        mm = MultiMethod([self.sync1, self.sync2], 'my_method', 'help')
        assert self.sync1.called_with is None
        assert self.sync2.called_with is None
        mm('a', 1, kw=2)
        assert self.sync1.called_with == (('a', 1), {'kw': 2})
        assert self.sync2.called_with == (('a', 1), {'kw': 2})

    async def test_async(self):
        mm = MultiMethod([self.async1, self.async2], 'my_method', 'help')
        assert self.async1.called_with is None
        assert self.async2.called_with is None
        await mm('a', 1, kw=2)
        assert self.async1.called_with == (('a', 1), {'kw': 2})
        assert self.async2.called_with == (('a', 1), {'kw': 2})
