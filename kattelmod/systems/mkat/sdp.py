"""Components for a standalone version of the SDP subsystem."""

import json
from typing import List, Optional

import aiokatcp
from katpoint import Antenna

from kattelmod.clock import get_clock, real_timeout
from kattelmod.component import (
    ComponentNotReadyError,
    KATCPComponent,
    TargetObserverMixin,
    TelstateUpdatingComponent,
)
from kattelmod.session import CaptureState
from .fake import Subarray as _Subarray


class CorrelatorBeamformer(TargetObserverMixin, TelstateUpdatingComponent):
    def __init__(self) -> None:
        super().__init__()
        self._initialise_attributes(locals())
        self.target = 'Zenith, azel, 0, 90'
        self.auto_delay_enabled = True
        self._add_dummy_methods('capture_start capture_stop product_deconfigure')

    async def product_configure(self, endpoint: str) -> None:
        pass


class ScienceDataProcessor(KATCPComponent):
    def __init__(self, master_controller: str, config: dict) -> None:
        super().__init__(master_controller)
        self._initialise_attributes(locals())
        self._product_controller = ''
        self.subarray_product = ''

    def _validate(self, post_configure: bool = True) -> None:
        if not self._client:
            raise ComponentNotReadyError('SDP master controller not connected via KATCP')
        if post_configure and not self.subarray_product:
            raise ComponentNotReadyError('SDP data product not configured')

    async def get_capture_state(self, subarray_product: str) -> CaptureState:
        self._validate(post_configure=False)
        try:
            msg, _ = await self._client.request('capture-status', subarray_product)
            lookup = {b'idle': CaptureState.CONFIGURED,
                      b'init_wait': CaptureState.INITED,
                      b'capturing': CaptureState.STARTED}
            return lookup.get(msg[0], CaptureState.UNKNOWN)
        except aiokatcp.FailReply:
            return CaptureState.UNCONFIGURED

    async def product_configure(self, sub: _Subarray, receptors: List[Antenna],
                                start_time: Optional[float] = None) -> CaptureState:
        subarray_product = f'array_{sub.sub_nr}_{sub.product}'
        self._validate(post_configure=False)
        initial_state = await self.get_capture_state(subarray_product)
        config = self.config
        if not isinstance(config, dict):
            config = json.loads(config)
        # Insert the antenna list, antenna positions and clock information
        config.setdefault('simulation', {})
        if get_clock().rate != 1.0:
            config['simulation']['clock_ratio'] = get_clock().rate
        if start_time is not None:
            config['simulation']['start_time'] = start_time
        for output in list(config['outputs'].values()):
            if output['type'] == 'sim.cbf.antenna_channelised_voltage':
                output['antennas'] = [receptor.description for receptor in receptors]
            # Insert the dump rate
            if output['type'] == 'sdp.vis' and 'output_int_time' not in output:
                output['output_int_time'] = 1.0 / sub.dump_rate
        try:
            async with real_timeout(300):
                msg, _ = await self._client.request(
                    'product-configure', subarray_product, json.dumps(config))
            product_host = msg[1].decode('utf-8')
            product_port = msg[2].decode('utf-8')
            self._product_controller = f'{product_host}:{product_port}'
        except aiokatcp.FailReply as exc:
            raise ComponentNotReadyError("Failed to configure product: " + str(exc)) from None
        self.subarray_product = subarray_product
        return initial_state

    async def product_deconfigure(self) -> None:
        self._validate()
        async with real_timeout(300):
            await self._client.request('product-deconfigure', self.subarray_product)

    async def get_telstate(self) -> str:
        self._validate()
        try:
            msg, _ = await self._client.request('telstate-endpoint', self.subarray_product)
            return msg[0].decode('utf-8')
        except aiokatcp.FailReply as exc:
            raise ComponentNotReadyError('Could not obtain telstate endpoint') from exc

    async def capture_init(self) -> None:
        self._validate()
        async with real_timeout(10):
            await self._client.request('capture-init', self.subarray_product)

    async def capture_done(self) -> None:
        self._validate()
        async with real_timeout(300):
            await self._client.request('capture-done', self.subarray_product)
