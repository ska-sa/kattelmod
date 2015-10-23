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

    def product_configure(self, product, dump_rate, receptors, sub_nr):
        self.subarray_product = 'array_{}_{}'.format(sub_nr, product)
        if not self._client:
            raise ValueError('SDP master controller not connected via KATCP')
        self._client.req.data_product_configure(self.subarray_product,
                                                receptors, 0, dump_rate, 0,
                                                self.cbf_spead, ':7147')

    def capture_init(self):
        if not self._client:
            raise ValueError('SDP master controller not connected via KATCP')
        if not self.subarray_product:
            raise ValueError('SDP data product not configured')
        self._client.req.capture_init(self.subarray_product)

    def capture_done(self):
        if not self._client:
            raise ValueError('SDP master controller not connected via KATCP')
        if not self.subarray_product:
            raise ValueError('SDP data product not configured')
        self._client.req.capture_done(self.subarray_product)


class Observation(TelstateUpdatingComponent):
    def __init__(self):
        super(Observation, self).__init__()
        self._initialise_attributes(locals())
        self.label = ''
        self.params = {}
        self.script_log = ''
