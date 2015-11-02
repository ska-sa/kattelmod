"""Components for a standalone version of the SDP subsystem."""

from kattelmod.component import KATCPComponent, TelstateUpdatingComponent
from katpoint import Target


class CorrelatorBeamformer(TelstateUpdatingComponent):
    def __init__(self):
        super(CorrelatorBeamformer, self).__init__()
        self._initialise_attributes(locals())
        self.target = 'Zenith, azel, 0, 90'
        self.auto_delay_enabled = True

    @property
    def target(self):
        return self._target
    @target.setter
    def target(self, target):
        self._target = Target(target) if target else None

    def capture_start(self):
        pass

    def capture_stop(self):
        pass


class ScienceDataProcessor(KATCPComponent):
    def __init__(self, master_controller, cbf_spead):
        super(ScienceDataProcessor, self).__init__(master_controller)
        self._initialise_attributes(locals())
        self.subarray_product = ''

    def _validate(self):
        if not self._client:
            raise ValueError('SDP master controller not connected via KATCP')
        if not self.subarray_product:
            raise ValueError('SDP data product not configured')

    def product_configure(self, product, dump_rate, receptors, sub_nr):
        self.subarray_product = 'array_{}_{}'.format(sub_nr, product)
        # Kludge to get semi-decent channels (as long as > 0 SDPMC will accept it)
        channels = 4096 if product.endswith('4k') else \
                  16384 if product.endswith('16k') else 1
        self._validate()
        prod_conf = self._client.req.data_product_configure
        msg = prod_conf(self.subarray_product, receptors, channels, dump_rate,
                        0, self.cbf_spead, ':7147', timeout=10)
        if not msg.succeeded:
            self.subarray_product = ''

    def product_deconfigure(self):
        self._validate()
        prod_conf = self._client.req.data_product_configure
        prod_conf(self.subarray_product, '', timeout=10)

    def get_telstate(self):
        self._validate()
        msg = self._client.req.telstate_endpoint(self.subarray_product)
        return msg.reply.arguments[1] if msg.succeeded else ''

    def capture_init(self):
        self._validate()
        self._client.req.capture_init(self.subarray_product)

    def capture_done(self):
        self._validate()
        self._client.req.capture_done(self.subarray_product, timeout=10)


class Observation(TelstateUpdatingComponent):
    def __init__(self):
        super(Observation, self).__init__()
        self._initialise_attributes(locals())
        self.label = ''
        self.params = {}
        self.script_log = ''
