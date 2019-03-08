from kattelmod.session import CaptureSession as BaseCaptureSession, CaptureState
from kattelmod.telstate import TelescopeState, FakeTelescopeState


class CaptureSession(BaseCaptureSession):
    """Capture session for the MeerKAT system."""

    def argparser(self, *args, **kwargs):
        parser = super(CaptureSession, self).argparser(*args, **kwargs)
        parser.add_argument('--telstate')
        return parser

    async def _get_telstate(self, args):
        if getattr(args, 'telstate', None):
            endpoint = args.telstate
        elif 'sdp' in self:
            endpoint = await self.sdp.get_telstate()
        else:
            endpoint = ''
        return None if not endpoint else TelescopeState(endpoint) \
            if endpoint != 'fake' else FakeTelescopeState()

    async def product_configure(self, args):
        initial_state = CaptureState.UNKNOWN
        if ('sub', 'sdp', 'ants') in self:
            ants = [comp.observer for comp in self.ants]
            await self.sdp._start()
            prod_conf = self.sdp.product_configure
            initial_state = await prod_conf(self.sub, sorted(ants))
        self._telstate = self.components._telstate = self._get_telstate(args)
        # The obs telstate is only configured on capture_init since it needs
        # a capture block ID view - disable it for now to avoid pollution
        if 'obs' in self:
            self.obs._telstate = None
        return initial_state

    async def capture_init(self):
        if 'sdp' in self:
            await self.sdp.capture_init()
            try:
                capture_block_id = self._telstate['sdp_capture_block_id']
            except KeyError:
                self.logger.warning('No sdp_capture_block_id in telstate - '
                                    'assuming simulated environment')
                capture_block_id = str(self.time())
            self.obs_params['capture_block_id'] = capture_block_id
            cb_telstate = self._telstate.view(capture_block_id)
            if 'obs' in self:
                self.obs.params = self.obs_params
                self.obs._telstate = cb_telstate
                self.obs._start()

    async def capture_start(self):
        if 'cbf' in self:
            await self.cbf.capture_start()

    async def capture_stop(self):
        if 'cbf' in self:
            await self.cbf.capture_stop()

    async def capture_done(self):
        if 'sdp' in self:
            await self.sdp.capture_done()

    async def product_deconfigure(self):
        if 'sdp' in self:
            await self.sdp.product_deconfigure()
