"""Components for a standalone version of the SDP subsystem."""

from kattelmod.component import (KATCPComponent, TelstateUpdatingComponent,
                                 TargetObserverMixin)
from kattelmod.session import CaptureState
from kattelmod.systems.mkat.fake import Observation


class ConnectionError(IOError):
    """Failed to connect to SDP controller."""


class ConfigurationError(ValueError):
    """Failed to configure SDP product."""


class CorrelatorBeamformer(TargetObserverMixin, TelstateUpdatingComponent):
    def __init__(self):
        super(CorrelatorBeamformer, self).__init__()
        self._initialise_attributes(locals())
        self.target = 'Zenith, azel, 0, 90'
        self.auto_delay_enabled = True
        self._add_dummy_methods('capture_start capture_stop')


class ScienceDataProcessor(KATCPComponent):
    def __init__(self, master_controller, cbf_spead):
        super(ScienceDataProcessor, self).__init__(master_controller)
        self._initialise_attributes(locals())
        self.subarray_product = ''

    def _validate(self, post_configure=True):
        if not self._client:
            raise ConnectionError('SDP master controller not connected via KATCP')
        if post_configure and not self.subarray_product:
            raise ConfigurationError('SDP data product not configured')

    def get_capturestate(self, subarray_product):
        self._validate(post_configure=False)
        msg = self._client.req.capture_status(subarray_product)
        lookup = {'idle': CaptureState.CONFIGURED,
                  'init_wait': CaptureState.INITED,
                  'capturing': CaptureState.STARTED}
        return lookup.get(msg.reply.arguments[1], CaptureState.UNKNOWN) \
               if msg.succeeded else CaptureState.UNCONFIGURED

    def product_configure(self, product, dump_rate, receptors, sub_nr):
        subarray_product = 'array_{}_{}'.format(sub_nr, product)
        # Kludge to get semi-decent channels (as long as > 0 SDPMC will accept it)
        channels = 4096 if product.endswith('4k') else \
                  16384 if product.endswith('16k') else 1
        self._validate(post_configure=False)
        initial_state = self.get_capturestate(subarray_product)
        prod_conf = self._client.req.data_product_configure
        msg = prod_conf(subarray_product, receptors, channels, dump_rate,
                        0, self.cbf_spead, ':7147', timeout=300)
        if not msg.succeeded:
            raise ConfigurationError("Failed to configure product: " +
                                     msg.reply.arguments[1])
        self.subarray_product = subarray_product
        return initial_state

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
        self._client.req.capture_init(self.subarray_product, timeout=10)

    def capture_done(self):
        self._validate()
        self._client.req.capture_done(self.subarray_product, timeout=10)
