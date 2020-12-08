import argparse
from typing import Any

import aioredis
from katpoint import Timestamp
from katsdptelstate.aio import TelescopeState
import katsdptelstate.aio.redis

from kattelmod.session import CaptureSession as BaseCaptureSession, CaptureState


class CaptureSession(BaseCaptureSession):
    """Capture session for the MeerKAT system."""

    def argparser(self, *args: Any, **kwargs: Any) -> argparse.ArgumentParser:
        parser = super().argparser(*args, **kwargs)
        parser.add_argument('--telstate')
        return parser

    async def _get_telstate(self, args: argparse.Namespace) -> TelescopeState:
        if getattr(args, 'telstate', None):
            endpoint = args.telstate
        elif 'sdp' in self:
            endpoint = await self.sdp.get_telstate()
        else:
            endpoint = ''

        if not endpoint:
            return None
        elif endpoint != 'fake':
            client = await aioredis.create_redis_pool(f'redis://{endpoint}')
            backend = katsdptelstate.aio.redis.RedisBackend(client)
            return TelescopeState(backend)
        else:
            return TelescopeState()

    async def product_configure(self, args: argparse.Namespace) -> CaptureState:
        initial_state = CaptureState.UNKNOWN
        if ('sub', 'sdp', 'ants') in self:
            ants = [comp.observer for comp in self.ants]
            await self.sdp._start()
            prod_conf = self.sdp.product_configure
            start_time = Timestamp(args.start_time).secs if args.start_time else None
            initial_state = await prod_conf(self.sub, sorted(ants), start_time)
        self._telstate = self.components._telstate = await self._get_telstate(args)
        # The obs telstate is only configured on capture_init since it needs
        # a capture block ID view - disable it for now to avoid pollution
        if 'obs' in self:
            self.obs._telstate = None
        return initial_state

    async def capture_init(self) -> None:
        if 'sdp' in self:
            await self.sdp.capture_init()
            try:
                capture_block_id = await self._telstate['sdp_capture_block_id']
            except KeyError:
                self.logger.warning('No sdp_capture_block_id in telstate - '
                                    'assuming simulated environment')
                capture_block_id = str(self.time())
            self.obs_params['capture_block_id'] = capture_block_id
            cb_telstate = self._telstate.view(capture_block_id)
            if 'obs' in self:
                self.obs.params = self.obs_params
                self.obs._telstate = cb_telstate
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
        if self._telstate:
            self._telstate.backend.close()
            await self._telstate.backend.wait_closed()
        if 'sdp' in self:
            await self.sdp.product_deconfigure()
