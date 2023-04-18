import argparse
from typing import Any, Iterable, Union

from katpoint import Timestamp
from katsdptelstate.aio import TelescopeState
from katsdptelstate.aio.redis import RedisBackend

from kattelmod.session import CaptureSession as BaseCaptureSession, CaptureState
from kattelmod.component import Component, MultiComponent


class CaptureSession(BaseCaptureSession):
    """Capture session for the MeerKAT system."""

    def __init__(self, components: Union[MultiComponent, Iterable[Component]] = ()) -> None:
        super().__init__(components)
        # Start off with a "fake" in-memory telstate
        self.telstate = self.components._telstate = TelescopeState()

    def argparser(self, *args: Any, **kwargs: Any) -> argparse.ArgumentParser:
        parser = super().argparser(*args, **kwargs)
        parser.add_argument('--telstate', help="Override telstate (host:port or 'fake')")
        return parser

    async def _set_telstate(self, args: argparse.Namespace) -> None:
        """Determine telstate endpoint and connect to it if not fake."""
        if getattr(args, 'telstate', None):
            endpoint = args.telstate
        elif 'sdp' in self:
            endpoint = await self.sdp.get_telstate()
        else:
            endpoint = 'fake'

        if endpoint != 'fake':
            backend = await RedisBackend.from_url(f'redis://{endpoint}')
            telstate = TelescopeState(backend)
            self.telstate = self.components._telstate = telstate

    async def product_configure(self, args: argparse.Namespace) -> CaptureState:
        initial_state = CaptureState.UNKNOWN
        if ('sub', 'sdp', 'ants') in self:
            ants = [comp.observer for comp in self.ants]
            await self.sdp._start()
            prod_conf = self.sdp.product_configure
            start_time = Timestamp(args.start_time).secs if args.start_time else None
            initial_state = await prod_conf(self.sub, sorted(ants), start_time)
            if 'cbf' in self:
                product_controller = getattr(self.sdp, '_product_controller', '')
                await self.cbf.product_configure(product_controller)
        await self._set_telstate(args)
        # The obs telstate is only configured on capture_init since it needs
        # a capture block ID view - disable it for now to avoid pollution
        if 'obs' in self:
            self.obs._telstate = None
        return initial_state

    async def capture_init(self) -> None:
        if 'sdp' in self:
            await self.sdp.capture_init()
            capture_block_id = await self.telstate['sdp_capture_block_id']
            self.obs_params['capture_block_id'] = capture_block_id
            cb_telstate = self.telstate.view(capture_block_id)
            self.telstate = self.components._telstate = cb_telstate
            if 'obs' in self:
                self.obs.params = self.obs_params
                await self.obs._start()

    async def capture_start(self) -> None:
        if 'cbf' in self:
            await self.cbf.capture_start()

    async def capture_stop(self) -> None:
        if 'cbf' in self:
            await self.cbf.capture_stop()

    async def capture_done(self) -> None:
        if 'sdp' in self:
            await self.sdp.capture_done()

    async def product_deconfigure(self) -> None:
        self.telstate.backend.close()
        await self.telstate.backend.wait_closed()
        if 'cbf' in self:
            await self.cbf.product_deconfigure()
        if 'sdp' in self:
            await self.sdp.product_deconfigure()
