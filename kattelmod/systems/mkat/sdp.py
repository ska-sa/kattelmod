"""Components for a standalone version of the SDP subsystem."""

import json

from kattelmod.component import (KATCPComponent, TelstateUpdatingComponent,
                                 TargetObserverMixin)
from kattelmod.session import CaptureState


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
    def __init__(self, master_controller, config):
        super(ScienceDataProcessor, self).__init__(master_controller)
        self._initialise_attributes(locals())
        self.subarray_product = ''

    def _validate(self, post_configure=True):
        if not self._client:
            raise ConnectionError('SDP master controller not connected via KATCP')
        if post_configure and not self.subarray_product:
            raise ConfigurationError('SDP data product not configured')

    def get_capture_state(self, subarray_product):
        self._validate(post_configure=False)
        msg = self._client.req.capture_status(subarray_product)
        lookup = {'idle': CaptureState.CONFIGURED,
                  'init_wait': CaptureState.INITED,
                  'capturing': CaptureState.STARTED}
        return lookup.get(msg.reply.arguments[1], CaptureState.UNKNOWN) \
            if msg.succeeded else CaptureState.UNCONFIGURED

    def product_configure(self, sub, receptors):
        subarray_product = 'array_{}_{}'.format(sub.sub_nr, sub.product)
        self._validate(post_configure=False)
        initial_state = self.get_capture_state(subarray_product)
        config = self.config
        if not isinstance(config, dict):
            config = json.loads(config)
        # Insert the antenna list and antenna positions
        for input_ in config['inputs'].values():
            if input_['type'] == 'cbf.antenna_channelised_voltage':
                input_['antennas'] = [receptor.name for receptor in receptors]
            if input_['type'] in ['cbf.baseline_correlation_products',
                                  'cbf.tied_array_channelised_voltage']:
                simulate = input_.get('simulate', False)
                if simulate is True:
                    simulate = input_['simulate'] = {}  # Upgrade to 1.1 API
                if isinstance(simulate, dict):
                    simulate['antennas'] = [receptor.description for receptor in receptors]
        # Insert the dump rate
        for output in config['outputs'].values():
            if output['type'] in ['sdp.l0', 'sdp.vis']:
                output['output_int_time'] = 1.0 / sub.dump_rate
        msg = self._client.req.product_configure(subarray_product, json.dumps(config),
                                                 timeout=300)
        if not msg.succeeded:
            raise ConfigurationError("Failed to configure product: " +
                                     msg.reply.arguments[1])
        self.subarray_product = subarray_product
        return initial_state

    def product_deconfigure(self):
        self._validate()
        prod_conf = self._client.req.product_deconfigure
        prod_conf(self.subarray_product, timeout=300)

    def get_telstate(self):
        self._validate()
        msg = self._client.req.telstate_endpoint(self.subarray_product)
        # XXX log connection problems
        return msg.reply.arguments[1] if msg.succeeded else ''

    def capture_init(self):
        self._validate()
        self._client.req.capture_init(self.subarray_product, timeout=10)

    def capture_done(self):
        self._validate()
        self._client.req.capture_done(self.subarray_product, timeout=300)
