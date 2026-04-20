import argparse
import hashlib
from pathlib import Path
from typing import Any, Iterable, Union

from katpoint import Timestamp
from katsdptelstate.aio import TelescopeState
from katsdptelstate.aio.redis import RedisBackend

from kattelmod.session import CaptureSession as BaseCaptureSession, CaptureState
from kattelmod.component import Component, MultiComponent

VLBI_EXPERIMENT_KEY = "vlbi_experiment"
VLBI_CATALOGUE_CONTENT_KEY = "vlbi_catalogue_content"
VLBI_CATALOGUE_SHA256_KEY = "vlbi_catalogue_sha256"
VLBI_CATALOGUE_NAME_KEY = "vlbi_catalogue_name"
VLBI_CATALOGUE_FORMAT_KEY = "vlbi_catalogue_format"


def _infer_vlbi_experiment(catalogue_text: str, catalogue_name: str) -> str:
    for raw_line in catalogue_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("#"):
            continue
        tokens = line[1:].strip().split()
        if len(tokens) >= 2 and tokens[0].upper() == "EXPERIMENT":
            return tokens[1].strip().lower()
    stem = Path(catalogue_name).stem
    if stem.lower().startswith("vlbi_cat_"):
        stem = stem[len("vlbi_cat_") :]
    return stem.strip().lower()


class CaptureSession(BaseCaptureSession):
    """Capture session for the MeerKAT system."""

    def __init__(self, components: Union[MultiComponent, Iterable[Component]] = ()) -> None:
        super().__init__(components)
        # Start off with a "fake" in-memory telstate
        self.telstate = self.components._telstate = TelescopeState()

    def argparser(self, *args: Any, **kwargs: Any) -> argparse.ArgumentParser:
        parser = super().argparser(*args, **kwargs)
        parser.add_argument('--telstate', help="Override telstate (host:port or 'fake')")
        parser.add_argument(
            '--vlbi-catalogue',
            help="Path to a per-observation VLBI catalogue CSV to serialize into capture-block telstate.",
        )
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
            self.telstate = self.components._telstate = TelescopeState(backend)

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
        self.state = CaptureState.CONFIGURED
        return initial_state

    async def capture_init(self) -> None:
        if 'sdp' in self:
            await self.sdp.capture_init()
            capture_block_id = await self.telstate['sdp_capture_block_id']
            self.obs_params['capture_block_id'] = capture_block_id
            self.telstate = self.telstate.view(capture_block_id)
            vlbi_catalogue = self.obs_params.pop('vlbi_catalogue', None)
            if vlbi_catalogue:
                catalogue_path = Path(str(vlbi_catalogue)).expanduser().resolve()
                catalogue_text = catalogue_path.read_text(encoding="utf-8")
                catalogue_name = catalogue_path.name
                catalogue_sha256 = hashlib.sha256(catalogue_text.encode("utf-8")).hexdigest()
                vlbi_experiment = _infer_vlbi_experiment(catalogue_text, catalogue_name)
                vlbi_metadata = self.obs_params.get('vlbi', {})
                if not isinstance(vlbi_metadata, dict):
                    vlbi_metadata = {}
                vlbi_metadata = dict(vlbi_metadata)
                vlbi_metadata.update(
                    {
                        "experiment": vlbi_experiment,
                        "catalogue_name": catalogue_name,
                        "catalogue_sha256": catalogue_sha256,
                        "catalogue_format": "csv",
                    }
                )
                self.obs_params['vlbi'] = vlbi_metadata
                await self.telstate.add(VLBI_EXPERIMENT_KEY, vlbi_experiment, immutable=True)
                await self.telstate.add(VLBI_CATALOGUE_NAME_KEY, catalogue_name, immutable=True)
                await self.telstate.add(VLBI_CATALOGUE_FORMAT_KEY, "csv", immutable=True)
                await self.telstate.add(VLBI_CATALOGUE_SHA256_KEY, catalogue_sha256, immutable=True)
                await self.telstate.add(VLBI_CATALOGUE_CONTENT_KEY, catalogue_text, immutable=True)
            if 'obs' in self:
                self.obs._telstate = self.telstate
                self.obs.params = self.obs_params
                await self.obs._start()
        self.state = CaptureState.INITED

    async def capture_start(self) -> None:
        if 'cbf' in self:
            await self.cbf.capture_start()
        self.state = CaptureState.STARTED

    async def capture_stop(self) -> None:
        if 'cbf' in self:
            await self.cbf.capture_stop()
        self.state = CaptureState.INITED

    async def capture_done(self) -> None:
        if 'sdp' in self:
            await self.sdp.capture_done()
        self.telstate = self.telstate.root()
        if 'obs' in self:
            self.obs._telstate = None
        self.state = CaptureState.CONFIGURED

    async def product_deconfigure(self) -> None:
        self.telstate.backend.close()
        await self.telstate.backend.wait_closed()
        if 'cbf' in self:
            await self.cbf.product_deconfigure()
        if 'sdp' in self:
            await self.sdp.product_deconfigure()
        self.state = CaptureState.UNCONFIGURED
