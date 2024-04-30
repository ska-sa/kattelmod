from kattelmod.clock import real_timeout
from kattelmod.component import (
    ComponentNotReadyError,
    KATCPComponent,
    TargetObserverMixin,
    TelstateUpdatingComponent,
)


class CorrelatorBeamformer(TargetObserverMixin, TelstateUpdatingComponent):
    def __init__(self) -> None:
        super().__init__()
        self._client = None
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

    async def capture_start(self) -> None:
        self._validate()
        stream = 'baseline_correlation_products'
        async with real_timeout(10):
            await self._client._client.request('capture-start', stream)

    async def capture_stop(self) -> None:
        self._validate()
        stream = 'baseline_correlation_products'
        async with real_timeout(10):
            await self._client._client.request('capture-stop', stream)
