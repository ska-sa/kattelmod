from kattelmod.clock import real_timeout
from kattelmod.component import (
    ComponentNotReadyError,
    KATCPComponent,
    TargetObserverMixin,
    TelstateUpdatingComponent,
)


class CorrelatorBeamformer(TargetObserverMixin, TelstateUpdatingComponent):
    _CAPTURE_STREAM_PREFIXES = (
        "baseline_correlation_products",
        "tied_array_channelised_voltage",
        "tied_array_resampled_voltage",
    )

    def __init__(self) -> None:
        super().__init__()
        self._client = None
        self._active_capture_streams: list[str] = []
        self._initialise_attributes(locals())
        self.target = 'Zenith, azel, 0, 90'
        self.auto_delay_enabled = True

    def _validate(self) -> None:
        if not self._client:
            raise ComponentNotReadyError(
                'Product controller not connected via KATCP - configure CBF first'
            )

    async def product_configure(self, endpoint: str) -> None:
        if self._client is not None:
            raise ComponentNotReadyError(
                f'Product controller already configured ({self._client._endpoint})'
            )
        self._client = KATCPComponent(endpoint)
        await self._client._start()

    async def product_deconfigure(self) -> None:
        if self._client:
            await self._client._stop()
            self._client = None
            self._active_capture_streams = []

    async def _capture_streams(self, state: str) -> list[str]:
        self._validate()
        async with real_timeout(10):
            _reply, informs = await self._client._client.request('capture-list')
        return [
            bytes(inform.arguments[0]).decode('utf-8')
            for inform in informs
            if len(inform.arguments) >= 3
            and bytes(inform.arguments[2]).decode('utf-8') == state
            and bytes(inform.arguments[0]).decode('utf-8').startswith(self._CAPTURE_STREAM_PREFIXES)
        ]

    async def capture_start(self) -> None:
        self._active_capture_streams = await self._capture_streams('down')
        for stream in self._active_capture_streams:
            async with real_timeout(10):
                await self._client._client.request('capture-start', stream)

    async def capture_stop(self) -> None:
        streams = self._active_capture_streams or await self._capture_streams('up')
        for stream in streams:
            async with real_timeout(10):
                await self._client._client.request('capture-stop', stream)
        self._active_capture_streams = []
