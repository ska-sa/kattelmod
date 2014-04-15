###############################################################################
# SKA South Africa (http://ska.ac.za/)                                        #
# Author: cam@ska.ac.za                                                       #
# Copyright @ 2013 SKA SA. All rights reserved.                               #
#                                                                             #
# THIS SOFTWARE MAY NOT BE COPIED OR DISTRIBUTED IN ANY FORM WITHOUT THE      #
# WRITTEN PERMISSION OF SKA SA.                                               #
###############################################################################
"""CaptureSession encompassing data capturing and standard observations with RTS.

This defines the :class:`CaptureSession` class, which encompasses the capturing
of data and the performance of standard scans with the RTS system. It also
provides a fake :class:`TimeSession` class, which goes through the motions in
order to time them, but without performing any real actions.

"""

import time
import logging
import sys
import os.path

import numpy as np
import katpoint
# This is used to document available spherical projections (and set them in case of TimeSession)
from katcorelib.targets import Offset

from .array import Array
from .katcp_client import KATClient
from .defaults import user_logger, activity_logger
from katmisc.utils.utils import dynamic_doc


# Obtain list of spherical projections and the default projection from antenna proxy
projections, default_proj = Offset.PROJECTIONS.keys(), Offset.DEFAULT_PROJECTION
# Move default projection to front of list
projections.remove(default_proj)
projections.insert(0, default_proj)


def ant_array(kat, ants, name='ants'):
    """Create sub-array of antennas from flexible specification.

    Parameters
    ----------
    kat : :class:`utility.KATCoreConn` object
        KAT connection object
    ants : :class:`Array` or :class:`KATClient` object, or list, or string
        Antennas specified by an Array object containing antenna devices, or
        a single antenna device or a list of antenna devices, or a string of
        comma-separated antenna names, or the string 'all' for all antennas
        controlled via the KAT connection associated with this session

    Returns
    -------
    array : :class:`Array` object
        Array object containing selected antenna devices

    Raises
    ------
    ValueError
        If antenna with a specified name is not found on KAT connection object

    """
    if isinstance(ants, Array):
        return ants
    elif isinstance(ants, KATClient):
        return Array(name, [ants])
    elif isinstance(ants, basestring):
        if ants.strip() == 'all':
            return kat.ants
        else:
            try:
                return Array(name, [getattr(kat, ant.strip()) for ant in ants.split(',')])
            except AttributeError:
                raise ValueError("Antenna '%s' not found (i.e. no kat.%s exists)" % (ant, ant))
    else:
        # The default assumes that *ants* is a list of antenna devices
        return Array(name, ants)


def report_compact_traceback(tb):
    """Produce a compact traceback report."""
    print '--------------------------------------------------------'
    print 'Session interrupted while doing (most recent call last):'
    print '--------------------------------------------------------'
    while tb:
        f = tb.tb_frame
        print '%s %s(), line %d' % (f.f_code.co_filename, f.f_code.co_name, f.f_lineno)
        tb = tb.tb_next
    print '--------------------------------------------------------'


class ScriptLogHandler(logging.Handler):
    """Logging handler that writes logging records to HDF5 file via ingest.

    Parameters
    ----------
    data : :class:`KATClient` object
        Data proxy device for the session

    """
    def __init__(self, data):
        logging.Handler.__init__(self)
        self.data = data

    def emit(self, record):
        """Emit a logging record."""
        try:
            msg = self.format(record)
# XXX This probably has to go to cam2spead as a req/sensor combo [YES]
#            self.data.req.k7w_script_log(msg)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


class ObsParams(dict):
    """Dictionary-ish that writes observation parameters to CAM SPEAD stream.

    Parameters
    ----------
    data : :class:`KATClient` object
        Data proxy device for the session
    product : string
        Name of data product

    """
    def __init__(self, data, product):
        dict.__init__(self)
        self.data = data
        self.product = product

    def __setitem__(self, key, value):
        self.data.req.set_obs_param(self.product, key, repr(value))
        dict.__setitem__(self, key, value)


class RequestSensorError(Exception):
    """Critical request failed or critical sensor could not be read."""
    pass


class CaptureSessionBase(object):
    def get_ant_names(self):
        return ','.join(co for co in self.kat.controlled_objects
                        if co in self.kat.katconfig.arrays['ants'])


class CaptureSession(CaptureSessionBase):
    """Context manager that encapsulates a single data capturing session.

    A data capturing *session* results in a single data file, potentially
    containing multiple scans and compound scans. An *experiment* may consist of
    multiple sessions. This object ensures that the capturing process is
    started and completed cleanly, even if exceptions occur during the session.
    It also provides canned routines for simple observations such as tracks,
    single scans and raster scans on a specific source.

    The initialisation of the session object does basic preparation of the data
    capturing subsystem (ingest) and logging. It tries to do the minimum to
    enable data capturing. The experimental setup is usually completed by
    calling :meth:`standard_setup` on the instantiated session object.
    The actual data capturing only starts once :meth:`capture_start` is called.

    Parameters
    ----------
    kat : :class:`utility.KATCoreConn` object
        KAT connection object associated with this experiment
    product : string, optional
        Data product (unchanged by default)
    dump_rate : float, optional
        Correlator dump rate, in Hz (will be set by default)
    kwargs : dict, optional
        Ignore any other keyword arguments (simplifies passing options as dict)

    Raises
    ------
    ValueError
        If data proxy is not connected
    RequestSensorError
        If ingest system did not initialise or data product could not be selected

    """
    def __init__(self, kat, product=None, dump_rate=1.0, **kwargs):
        try:
            self.kat = kat
            # Hard-code the RTS data proxy for now
            data, katsys = kat.data_rts, kat.sys
            if not data.is_connected():
                raise ValueError("Data proxy '%s' is not connected "
                                 "(is the KAT system running?)" % (data.name,))
            self.data = self.dbe = data

            # Default settings for session parameters (in case standard_setup is not called)
            self.ants = None
            self.experiment_id = 'interactive'
            self.stow_when_done = False
            self.nd_params = {'diode': 'default', 'on': 0., 'off': 0., 'period': -1.}
            self.last_nd_firing = 0.
            self.output_file = ''
            self.horizon = 3.0
            # Requested dump period, replaced by actual value after capture started
            self.dump_period = self._requested_dump_period = 1.0 / dump_rate

            # # XXX last dump timestamp?
            # self._end_of_previous_session = data.sensor.k7w_last_dump_timestamp.get_value()

            # XXX Hard-code product name for now
            self.product = 'c856M32k' if product is None else product
            data.req.product_configure(self.product, dump_rate, timeout=330)

            # Enable logging to the new HDF5 file via the usual logger (using same formatting and filtering)
            self._script_log_handler = ScriptLogHandler(data)
            if len(user_logger.handlers) > 0:
                self._script_log_handler.setLevel(user_logger.handlers[0].level)
                self._script_log_handler.setFormatter(user_logger.handlers[0].formatter)
            user_logger.addHandler(self._script_log_handler)

            user_logger.info('==========================')
            user_logger.info('New data capturing session')
            user_logger.info('--------------------------')
            user_logger.info('Data proxy used = %s' % (data.name,))
            user_logger.info('Data product = %s' % (self.product,))

            # XXX file name? SB ID? Program block ID? -> [file via capture_done]
            # # Obtain the name of the file currently being written to
            # reply = data.req.k7w_get_current_file()
            # outfile = reply[1] if reply.succeeded else '<unknown file>'
            outfile = '<unknown file>'
            user_logger.info('Opened output file = %s' % (outfile,))
            user_logger.info('')

            activity_logger.info("----- Script starting %s (%s). Output file %s" % (sys.argv[0], ' '.join(sys.argv[1:]), outfile))

            # Log details of the script to the back-end
            self.obs_params = ObsParams(data, self.product)
            katsys.req.set_script_param('script-starttime', time.time())
            katsys.req.set_script_param('script-endtime', '')
            katsys.req.set_script_param('script-name', sys.argv[0])
            katsys.req.set_script_param('script-arguments', ' '.join(sys.argv[1:]))
            katsys.req.set_script_param('script-status', 'busy')
        except Exception, e:
            msg = 'CaptureSession failed to initialise (%s)' % (e,)
            user_logger.error(msg)
            activity_logger.info(msg)
            if hasattr(self, '_script_log_handler'):
                user_logger.removeHandler(self._script_log_handler)
            raise

    def __enter__(self):
        """Enter the data capturing session."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Exit the data capturing session, closing the data file."""
        if exc_value is not None:
            exc_msg = str(exc_value)
            msg = "Session interrupted by exception (%s%s)" % \
                  (exc_value.__class__.__name__,
                   (": '%s'" % (exc_msg,)) if exc_msg else '')
            if exc_type is KeyboardInterrupt:
                user_logger.warning(msg)
                activity_logger.warning(msg)
            else:
                user_logger.error(msg, exc_info=True)
                activity_logger.error(msg, exc_info=True)
            self.end(interrupted=True)
        else:
            self.end(interrupted=False)
        # Suppress KeyboardInterrupt so as not to scare the lay user,
        # but allow other exceptions that occurred in the body of with-statement
        if exc_type is KeyboardInterrupt:
            report_compact_traceback(traceback)
            return True
        else:
            return False

    def get_centre_freq(self):
        """Get RF (sky) frequency associated with middle CBF channel.

        Returns
        -------
        centre_freq : float
            Actual centre frequency in MHz (or NaN if something went wrong)

        """
        return self.data.sensor.delay_center_frequency.get_value() / 1e6

    def set_centre_freq(self, centre_freq):
        """Set RF (sky) frequency associated with middle CBF channel.

        Parameters
        ----------
        centre_freq : float
            Desired centre frequency in MHz

        """
        # This currently only sets the delay compensation reference frequency
        # XXX Hopefully this will also change downconversion frequency in future
        self.data.req.set_center_frequency(centre_freq * 1e6)

    def standard_setup(self, observer, description, experiment_id=None,
                       nd_params=None, stow_when_done=None, horizon=None, **kwargs):
        """Perform basic experimental setup including antennas, LO and dump rate.

        This performs the basic high-level setup that most experiments require.
        It should usually be called as the first step in a new session
        (unless the experiment has special requirements, such as holography).

        The user selects a subarray of antennas that will take part in the
        experiment, identifies him/herself and describes the experiment.
        Optionally, the user may also set the RF centre frequency, dump rate
        and noise diode firing strategy, amongst others. All optional settings
        are left unchanged if unspecified, except for the dump rate, which has
        to be set (due to the fact that there is currently no way to determine
        the dump rate...).

        The antenna specification *ants* do not have a default, which forces the
        user to specify them explicitly. This is for safety reasons, to remind
        the user of which antennas will be moved around by the script. The
        *observer* and *description* similarly have no default, to force the
        user to document the observation to some extent.

        Parameters
        ----------
        ants : :class:`Array` or :class:`KATClient` object, or list, or string
            Antennas that will participate in the capturing session, as an Array
            object containing antenna devices, or a single antenna device or a
            list of antenna devices, or a string of comma-separated antenna
            names, or the string 'all' for all antennas controlled via the
            KAT connection associated with this session
        observer : string
            Name of person doing the observation
        description : string
            Short description of the purpose of the capturing session
        experiment_id : string, optional
            Experiment ID, a unique string used to link the data files of an
            experiment together with blog entries, etc. (unchanged by default)
        nd_params : dict, optional
            Dictionary containing parameters that control firing of the noise
            diode during canned commands. These parameters are in the form of
            keyword-value pairs, and matches the parameters of the
            :meth:`fire_noise_diode` method. This is unchanged by default
            (typically disabling automatic firing).
        stow_when_done : {False, True}, optional
            If True, stow the antennas when the capture session completes
            (unchanged by default)
        horizon : float, optional
            Elevation limit serving as horizon for session, in degrees
        kwargs : dict, optional
            Ignore any other keyword arguments (simplifies passing options as dict)

        Raises
        ------
        ValueError
            If antenna with a specified name is not found on KAT connection object
        RequestSensorError
            If Data centre frequency could not be set

        """
        # XXX Add band selection on digitiser

        # Create references to allow easy copy-and-pasting from this function
        session, kat, data, katsys = self, self.kat, self.data, self.kat.sys

        session.ants = ants = ant_array(kat, self.get_ant_names())
        ant_names = [ant.name for ant in ants]
        # Override provided session parameters (or initialize them from existing parameters if not provided)
        session.experiment_id = experiment_id = session.experiment_id if experiment_id is None else experiment_id
        session.nd_params = nd_params = session.nd_params if nd_params is None else nd_params
        session.stow_when_done = stow_when_done = session.stow_when_done if stow_when_done is None else stow_when_done
        session.horizon = session.horizon if horizon is None else horizon

        # Prep capturing system
        data.req.capture_init(self.product)

        # Setup strategies for the sensors we might be wait()ing on
        ants.req.sensor_sampling('lock', 'event')
        ants.req.sensor_sampling('scan.status', 'event')
        ants.req.sensor_sampling('mode', 'event')
        # XXX can we still get these sensors somewhere?
        # data.req.sensor_sampling('k7w.spead_dump_period', 'event')
        # data.req.sensor_sampling('k7w.last_dump_timestamp', 'event')

        centre_freq = self.get_centre_freq()

        # Check this...
        # # The data proxy needs to know the dump period (in s) as well as the RF centre frequency
        # # of 400-MHz downconverted band (in Hz), which is used for fringe stopping / delay tracking
        # data.req.capture_setup(1. / dump_rate, session.get_centre_freq(200.0) * 1e6)

        user_logger.info('Antennas used = %s' % (' '.join(ant_names),))
        user_logger.info('Observer = %s' % (observer,))
        user_logger.info("Description ='%s'" % (description,))
        user_logger.info('Experiment ID = %s' % (experiment_id,))
        user_logger.info('Data product = %s' % (self.product,))
        user_logger.info("RF centre frequency = %g MHz, dump rate = %g Hz" % (centre_freq, 1.0 / self.dump_period))
        if nd_params['period'] > 0:
            nd_info = "Will switch '%s' noise diode on for %g s and off for %g s, every %g s if possible" % \
                      (nd_params['diode'], nd_params['on'], nd_params['off'], nd_params['period'])
        elif nd_params['period'] == 0:
            nd_info = "Will switch '%s' noise diode on for %g s and off for %g s at every opportunity" % \
                      (nd_params['diode'], nd_params['on'], nd_params['off'])
        else:
            nd_info = "Noise diode will not fire automatically"
        user_logger.info(nd_info + " while performing canned commands")

        # Send script options to SPEAD stream
        self.obs_params['observer'] = observer
        self.obs_params['description'] = description
        self.obs_params['experiment_id'] = experiment_id
        self.obs_params['nd_params'] = nd_params
        self.obs_params['stow_when_done'] = stow_when_done
        self.obs_params['horizon'] = session.horizon
        self.obs_params['centre_freq'] = centre_freq
        self.obs_params['product'] = self.product
        self.obs_params.update(kwargs)
        # Send script options to CAM system
        katsys.req.set_script_param('script-ants', ','.join(ant_names))
        katsys.req.set_script_param('script-observer', observer)
        katsys.req.set_script_param('script-description', description)
        katsys.req.set_script_param('script-experiment-id', experiment_id)
        katsys.req.set_script_param('script-rf-params',
                                    'Centre freq=%g MHz, Dump rate=%g Hz' % (centre_freq, 1.0 / self.dump_period))
        katsys.req.set_script_param('script-nd-params', 'Diode=%s, On=%g s, Off=%g s, Period=%g s' %
                                    (nd_params['diode'], nd_params['on'], nd_params['off'], nd_params['period']))

        # If the CBF is simulated, it will have position update commands
        if hasattr(data.req, 'cbf_pointing_az') and hasattr(data.req, 'cbf_pointing_el'):

            def listener_actual_azim(update_seconds, value_seconds, status, value):
                #Listener callback now includes status, use it here
                if status == 'nominal':
                    data.req.cbf_pointing_az(value)

            def listener_actual_elev(update_seconds, value_seconds, status, value):
                #Listener callback now includes status, use it here
                if status == 'nominal':
                    data.req.cbf_pointing_el(value)

            first_ant = ants[0]
            # The minimum time between position updates is fraction of dump period to ensure fresh data at every dump
            update_period_seconds = 0.4 * self.dump_period
            # Tell the position sensors to report their values periodically at this rate
            first_ant.sensor.pos_actual_scan_azim.set_strategy('period', str(float(update_period_seconds)))
            first_ant.sensor.pos_actual_scan_elev.set_strategy('period', str(float(update_period_seconds)))
            # Tell the Data simulator where the first antenna is so that it can generate target flux at the right time
            first_ant.sensor.pos_actual_scan_azim.register_listener(listener_actual_azim, update_period_seconds)
            first_ant.sensor.pos_actual_scan_elev.register_listener(listener_actual_elev, update_period_seconds)
            user_logger.info("CBF simulator receives position updates from antenna '%s'" % (first_ant.name,))
        user_logger.info("--------------------------")

    def capture_start(self):
        """Start capturing data to HDF5 file."""
        # This starts the data product stream
        self.data.req.capture_start(self.product)

    def label(self, label):
        """Add timestamped label to HDF5 file.

        The label is typically a single word used to indicate the start of a
        new compound scan.

        """
        if label:
            self.data.req.set_obs_label(self.product, label)
            user_logger.info("New compound scan: '%s'" % (label,))

    def on_target(self, target):
        """Determine whether antennas are tracking a given target.

        If all connected antennas in the sub-array participating in the session
        have the given *target* as target and are locked in mode 'POINT', we
        conclude that the array is on target.

        Parameters
        ----------
        target : :class:`katpoint.Target` object or string
            Target to check, as an object or description string

        Returns
        -------
        on_target : {True, False}
            True if antennas are tracking the given target

        """
        if self.ants is None:
            return False
        # Turn target object into description string (or use string as is)
        target = getattr(target, 'description', target)
        for ant in self.ants:
            # Ignore disconnected antennas or ones with missing sensors
            if not ant.is_connected() or any([s not in ant.sensor for s in ('target', 'mode', 'lock')]):
                continue
            if (ant.sensor.target.get_value() != target) or (ant.sensor.mode.get_value() != 'POINT') or \
               (ant.sensor.lock.get_value() != '1'):
                return False
        return True

    def target_visible(self, target, duration=0., timeout=300.):
        """Check whether target is visible for given duration.

        This checks whether the *target* is currently above the session horizon
        and also above the horizon for the next *duration* seconds, taking into
        account the *timeout* on slewing to the target. If the target is not
        visible, an appropriate message is logged. The target location is not
        very accurate, as it does not include refraction, and this is therefore
        intended as a rough check only.

        Parameters
        ----------
        target : :class:`katpoint.Target` object or string
            Target to check, as an object or description string
        duration : float, optional
            Duration of observation of target, in seconds
        timeout : float, optional
            Timeout involved when antenna cannot reach the target

        Returns
        -------
        visible : {True, False}
            True if target is visible from all antennas for entire duration

        """
        if self.ants is None:
            return False
        # Convert description string to target object, or keep object as is
        target = target if isinstance(target, katpoint.Target) else katpoint.Target(target)
        horizon = katpoint.deg2rad(self.horizon)
        # Include an average time to slew to the target (worst case about 90 seconds, so half that)
        now = time.time() + 45.
        average_el, visible_before, visible_after = [], [], []
        # Ignore disconnected antennas or ones with missing sensors
        ant_descriptions = [ant.sensor.observer.get_value() for ant in self.ants
                            if ant.is_connected() and 'observer' in ant.sensor]
        # Also ignore antennas with empty or missing observer strings
        antennas = [katpoint.Antenna(descr) for descr in ant_descriptions if descr]
        if not antennas:
            user_logger.warning("No usable antennas found - target '%s' assumed to be down" % (target.name,))
            return False
        for antenna in antennas:
            az, el = target.azel(now, antenna)
            average_el.append(katpoint.rad2deg(el))
            # If not up yet, see if the target will pop out before the timeout
            if el < horizon:
                now += timeout
                az, el = target.azel(now, antenna)
            visible_before.append(el >= horizon)
            # Check what happens at end of observation
            az, el = target.azel(now + duration, antenna)
            visible_after.append(el >= horizon)
        if all(visible_before) and all(visible_after):
            return True
        always_invisible = any(~np.array(visible_before) & ~np.array(visible_after))
        if always_invisible:
            user_logger.warning("Target '%s' is never up during requested period (average elevation is %g degrees)" %
                                (target.name, np.mean(average_el)))
        else:
            user_logger.warning("Target '%s' will rise or set during requested period" % (target.name,))
        return False

    def fire_noise_diode(self, diode='coupler', on=10.0, off=10.0, period=0.0, align=True, announce=True):
        """Switch noise diode on and off.

        This switches the selected noise diode on and off for all the antennas
        doing the observation.

        The on and off durations can be specified. Additionally, setting the
        *period* allows the noise diode to be fired on a semi-regular basis. The
        diode will only be fired if more than *period* seconds have elapsed since
        the last firing. If *period* is 0, the diode is fired unconditionally.
        On the other hand, if *period* is negative it is not fired at all.

        Parameters
        ----------
        diode : {'coupler', 'pin'}
            Noise diode source to use (pin diode is situated in feed horn and
            produces high-level signal, while coupler diode couples into
            electronics after the feed at a much lower level)
        on : float, optional
            Minimum duration for which diode is switched on, in seconds
        off : float, optional
            Minimum duration for which diode is switched off, in seconds
        period : float, optional
            Minimum time between noise diode firings, in seconds. (The maximum
            time is determined by the duration of individual slews and scans,
            which are considered atomic and won't be interrupted.) If 0, fire
            diode unconditionally. If negative, don't fire diode at all.
        align : {True, False}, optional
            True if noise diode transitions should be aligned with correlator
            dump boundaries, or False if they should happen as soon as possible
        announce : {True, False}, optional
            True if start of action should be announced, with details of settings

        Returns
        -------
        fired : {True, False}
            True if noise diode fired

        Notes
        -----
        When the function returns, data will still be recorded to the HDF5 file.
        The specified *off* duration is therefore a minimum value. Remember to
        run :meth:`end` to close the file and finally stop the observation
        (automatically done when this object is used in a with-statement)!

        """
        # XXX This needs a rethink...
        return False

#
#         if self.ants is None:
#             raise ValueError('No antennas specified for session - please run session.standard_setup first')
#         # Create references to allow easy copy-and-pasting from this function
#         session, kat, ants, data, dump_period = self, self.kat, self.ants, self.data, self.dump_period
#
#         # Wait for the dump period to become known, as it is needed to set a good timeout for the first dump
#         if dump_period == 0.0:
#             if not data.wait('k7w_spead_dump_period', lambda sensor: sensor.value > 0, timeout=1.5 * session._requested_dump_period, poll_period=0.2 * session._requested_dump_period):
#                 dump_period = session.dump_period = session._requested_dump_period
#                 user_logger.warning('SPEAD metadata header is overdue at ingest - noise diode will be out of sync')
#             else:
#                 # Get actual dump period in seconds (as opposed to the requested period)
#                 dump_period = session.dump_period = data.sensor.k7w_spead_dump_period.get_value()
#                 # This can still go wrong if the sensor times out - again fall back to requested period
#                 if dump_period is None:
#                     dump_period = session.dump_period = session._requested_dump_period
#                     user_logger.warning('Could not read actual dump period - noise diode will be out of sync')
#         # Wait for the first correlator dump to appear, both as a check that capturing works and to align noise diode
#         last_dump = data.sensor.k7w_last_dump_timestamp.get_value()
#         if last_dump == session._end_of_previous_session or last_dump is None:
#             user_logger.info('waiting for correlator dump to arrive')
#             # Wait for the first correlator dump to appear
#             if not data.wait('k7w_last_dump_timestamp', lambda sensor: sensor.value > session._end_of_previous_session,
#                             timeout=2.2 * dump_period, poll_period=0.2 * dump_period):
#                 last_dump = time.time()
#                 user_logger.warning('Correlator dump is overdue at k7_capture - noise diode will be out of sync')
#             else:
#                 last_dump = data.sensor.k7w_last_dump_timestamp.get_value()
#                 if last_dump is None:
#                     last_dump = time.time()
#                     user_logger.warning('Could not read last dump timestamp - noise diode will be out of sync')
#                 else:
#                     user_logger.info('correlator dump arrived')
#
#         # If period is non-negative, quit if it is not yet time to fire the noise diode
#         if period < 0.0 or (time.time() - session.last_nd_firing) < period:
#             return False
#
#         if align:
#             # Round "on" duration up to the nearest integer multiple of dump period
#             on = np.ceil(float(on) / dump_period) * dump_period
#             # The last fully complete dump is more than 1 dump period in the past
#             next_dump = last_dump + 2 * dump_period
#             # The delay in setting up noise diode firing - next dump should be at least this far in future
#             lead_time = 0.25
#             # Find next suitable dump boundary
#             now = time.time()
#             while next_dump < now + lead_time:
#                 next_dump += dump_period
#
#         if announce:
#             user_logger.info("Firing '%s' noise diode (%g seconds on, %g seconds off)" % (diode, on, off))
#         else:
#             user_logger.info('firing noise diode')
#
#         if align:
#             # Schedule noise diode switch-on on all antennas at the next suitable dump boundary
#             ants.req.rfe3_rfe15_noise_source_on(diode, 1, 1000 * next_dump, 0)
#             # If using Data simulator, fire the simulated noise diode for desired period to toggle power levels in output
#             if hasattr(data.req, 'data_fire_nd') and dump_period > 0:
#                 time.sleep(max(next_dump - time.time(), 0))
#                 data.req.data_fire_nd(np.ceil(float(on) / dump_period))
#             # Wait until the noise diode is on
#             time.sleep(max(next_dump + 0.5 * on - time.time(), 0))
#             # Schedule noise diode switch-off on all antennas a duration of "on" seconds later
#             ants.req.rfe3_rfe15_noise_source_on(diode, 0, 1000 * (next_dump + on), 0)
#             time.sleep(max(next_dump + on + off - time.time(), 0))
#             # Mark on -> off transition as last firing
#             session.last_nd_firing = next_dump + on
#         else:
#             # Switch noise diode on on all antennas
#             ants.req.rfe3_rfe15_noise_source_on(diode, 1, 'now', 0)
#             # If using Data simulator, fire the simulated noise diode for desired period to toggle power levels in output
#             if hasattr(data.req, 'data_fire_nd'):
#                 data.req.data_fire_nd(np.ceil(float(on) / dump_period))
#             time.sleep(on)
#             # Mark on -> off transition as last firing
#             session.last_nd_firing = time.time()
#             # Switch noise diode off on all antennas
#             ants.req.rfe3_rfe15_noise_source_on(diode, 0, 'now', 0)
#             time.sleep(off)
#
#         user_logger.info('noise diode fired')
#         return True

    def set_target(self, target):
        """Set target to use for tracking or scanning.

        This sets the target on all antennas involved in the session, as well as
        on the CBF (where it serves as delay-tracking centre). It also moves the
        test target in the Data simulator to match the requested target (if it is
        a stationary 'azel' type). The target is only set if it differs from the
        existing target.

        Parameters
        ----------
        target : :class:`katpoint.Target` object or string
            Target as an object or description string

        """
        if self.ants is None:
            raise ValueError('No antennas specified for session - please run session.standard_setup first')
        # Create references to allow easy copy-and-pasting from this function
        ants, data = self.ants, self.data
        # Convert description string to target object, or keep object as is
        target = target if isinstance(target, katpoint.Target) else katpoint.Target(target)

        for ant in ants:
            # Don't set the target unnecessarily as this upsets the antenna proxy, causing momentary loss of lock
            current_target = ant.sensor.target.get_value()
            if target != current_target:
                # Set the antenna target (antennas will already move there if in mode 'POINT')
                ant.req.target(target)
        # Provide target to the data proxy, which will use it as delay-tracking center
        current_target = data.sensor.target.get_value()
        if target != current_target:
            data.req.target(target)
        # If using Data simulator and target is azel type, move test target here (allows changes in correlation power)
        if hasattr(data.req, 'cbf_test_target') and target.body_type == 'azel':
            azel = katpoint.rad2deg(np.array(target.azel()))
            data.req.cbf_test_target(azel[0], azel[1], 100.)

    def track(self, target, duration=20.0, announce=True):
        """Track a target.

        This tracks the specified target with all antennas involved in the
        session.

        Parameters
        ----------
        target : :class:`katpoint.Target` object or string
            Target to track, as an object or description string
        duration : float, optional
            Minimum duration of track, in seconds
        announce : {True, False}, optional
            True if start of action should be announced, with details of settings

        Returns
        -------
        success : {True, False}
            True if track was successfully completed

        Notes
        -----
        When the function returns, the antennas will still track the target and
        data will still be recorded to the HDF5 file. The specified *duration*
        is therefore a minimum value. Remember to run :meth:`end` to close the
        file and finally stop the observation (automatically done when this
        object is used in a with-statement)!

        """
        if self.ants is None:
            raise ValueError('No antennas specified for session - please run session.standard_setup first')
        # Create references to allow easy copy-and-pasting from this function
        session, ants = self, self.ants
        # Convert description string to target object, or keep object as is
        target = target if isinstance(target, katpoint.Target) else katpoint.Target(target)

        if announce:
            user_logger.info("Initiating %g-second track on target '%s'" % (duration, target.name))
        if not session.target_visible(target, duration):
            user_logger.warning("Skipping track, as target '%s' will be below horizon" % (target.name,))
            return False

        session.set_target(target)

        session.fire_noise_diode(announce=False, **session.nd_params)

        # Avoid slewing if we are already on target
        if not session.on_target(target):
            user_logger.info('slewing to target')
            # Start moving each antenna to the target
            ants.req.mode('POINT')
            # Wait until they are all in position (with 5 minute timeout)
            ants.wait('lock', True, 300)
            user_logger.info('target reached')

            session.fire_noise_diode(announce=False, **session.nd_params)

        user_logger.info('tracking target')
        # Do nothing else for the duration of the track
        time.sleep(duration)
        user_logger.info('target tracked for %g seconds' % (duration,))

        session.fire_noise_diode(announce=False, **session.nd_params)
        return True

    @dynamic_doc("', '".join(projections), default_proj)
    def scan(self, target, duration=30.0, start=(-3.0, 0.0), end=(3.0, 0.0),
             index=-1, projection=default_proj, announce=True):
        """Scan across a target.

        This scans across a target with all antennas involved in the session.
        The scan starts at an offset of *start* degrees from the target and ends
        at an offset of *end* degrees. These offsets are calculated in a projected
        coordinate system (see *Notes* below). The scan lasts for *duration*
        seconds.

        Parameters
        ----------
        target : :class:`katpoint.Target` object or string
            Target to scan across, as an object or description string
        duration : float, optional
            Minimum duration of scan across target, in seconds
        start : sequence of 2 floats, optional
            Initial scan position as (x, y) offset in degrees (see *Notes* below)
        end : sequence of 2 floats, optional
            Final scan position as (x, y) offset in degrees (see *Notes* below)
        index : integer, optional
            Scan index, used for display purposes when this is part of a raster
        projection : {'%s'}, optional
            Name of projection in which to perform scan relative to target
            (default = '%s')
        announce : {True, False}, optional
            True if start of action should be announced, with details of settings

        Returns
        -------
        success : {True, False}
            True if scan was successfully completed

        Notes
        -----
        Take note that scanning is done in a projection on the celestial sphere,
        and the scan start and end are in the projected coordinates. The azimuth
        coordinate of a scan in azimuth will therefore change more than the
        *start* and *end* parameters suggest, especially at high elevations
        (unless the 'plate-carree' projection is used). This ensures that the
        same scan parameters will lead to the same qualitative scan for any
        position on the celestial sphere.

        When the function returns, the antennas will still track the end-point of
        the scan and data will still be recorded to the HDF5 file. The specified
        *duration* is therefore a minimum value. Remember to run :meth:`end` to
        close the file and finally stop the observation (automatically done when
        this object is used in a with-statement)!

        """
        if self.ants is None:
            raise ValueError('No antennas specified for session - please run session.standard_setup first')
        # Create references to allow easy copy-and-pasting from this function
        session, ants = self, self.ants
        # Convert description string to target object, or keep object as is
        target = target if isinstance(target, katpoint.Target) else katpoint.Target(target)
        scan_name = 'scan' if index < 0 else 'scan %d' % (index,)

        if announce:
            user_logger.info("Initiating %g-second scan across target '%s'" % (duration, target.name))
        if not session.target_visible(target, duration):
            user_logger.warning("Skipping scan, as target '%s' will be below horizon" % (target.name,))
            return False

        session.set_target(target)

        session.fire_noise_diode(announce=False, **session.nd_params)

        user_logger.info('slewing to start of %s' % (scan_name,))
        # Move each antenna to the start position of the scan
        ants.req.scan_asym(start[0], start[1], end[0], end[1], duration, projection)
        ants.req.mode('POINT')
        # Wait until they are all in position (with 5 minute timeout)
        ants.wait('lock', True, 300)
        user_logger.info('start of %s reached' % (scan_name,))

        session.fire_noise_diode(announce=False, **session.nd_params)

        user_logger.info('performing %s' % (scan_name,))
        # Start scanning the antennas
        ants.req.mode('SCAN')
        # Wait until they are all finished scanning (with 5 minute timeout)
        ants.wait('scan_status', 'after', 300)
        user_logger.info('%s complete' % (scan_name,))

        session.fire_noise_diode(announce=False, **session.nd_params)
        return True

    @dynamic_doc("', '".join(projections), default_proj)
    def raster_scan(self, target, num_scans=3, scan_duration=30.0, scan_extent=6.0, scan_spacing=0.5,
                    scan_in_azimuth=True, projection=default_proj, announce=True):
        """Perform raster scan on target.

        A *raster scan* is a series of scans across a target performed by all
        antennas involved in the session, scanning in either azimuth or
        elevation while the other coordinate is changed in steps for each scan.
        Each scan is offset by the same amount on both sides of the target along
        the scanning coordinate (and therefore has the same extent), and the
        scans are arranged symmetrically around the target in the non-scanning
        (stepping) direction. If an odd number of scans are done, the middle
        scan will therefore pass directly over the target. The default is to
        scan in azimuth and step in elevation, leading to a series of horizontal
        scans. Each scan is scanned in the opposite direction to the previous
        scan to save time. Additionally, the first scan always starts at the top
        left of the target, regardless of scan direction.

        Parameters
        ----------
        target : :class:`katpoint.Target` object or string
            Target to scan across, as an object or description string
        num_scans : integer, optional
            Number of scans across target (an odd number is better, as this will
            scan directly over the source during the middle scan)
        scan_duration : float, optional
            Minimum duration of each scan across target, in seconds
        scan_extent : float, optional
            Extent (angular length) of scan along scanning coordinate, in degrees
            (see *Notes* below)
        scan_spacing : float, optional
            Separation between each consecutive scan along the coordinate that is
            not scanned but stepped, in degrees
        scan_in_azimuth : {True, False}
            True if azimuth changes during scan while elevation remains fixed;
            False if scanning in elevation and stepping in azimuth instead
        projection : {'%s'}, optional
            Name of projection in which to perform scan relative to target
            (default = '%s')
        announce : {True, False}, optional
            True if start of action should be announced, with details of settings

        Returns
        -------
        success : {True, False}
            True if raster scan was successfully completed

        Notes
        -----
        Take note that scanning is done in a projection on the celestial sphere,
        and the scan extent and spacing apply to the projected coordinates.
        The azimuth coordinate of a scan in azimuth will therefore change more
        than the *scan_extent* parameter suggests, especially at high elevations.
        This ensures that the same scan parameters will lead to the same
        qualitative scan for any position on the celestial sphere.

        When the function returns, the antennas will still track the end-point of
        the last scan and data will still be recorded to the HDF5 file. The
        specified *scan_duration* is therefore a minimum value. Remember to run
        :meth:`end` to close the files and finally stop the observation
        (automatically done when this object is used in a with-statement)!

        """
        if self.ants is None:
            raise ValueError('No antennas specified for session - please run session.standard_setup first')
        # Create references to allow easy copy-and-pasting from this function
        session = self
        # Convert description string to target object, or keep object as is
        target = target if isinstance(target, katpoint.Target) else katpoint.Target(target)

        if announce:
            user_logger.info("Initiating raster scan (%d %g-second scans extending %g degrees) on target '%s'" %
                             (num_scans, scan_duration, scan_extent, target.name))
        # Calculate average time that noise diode is operated per scan, to add to scan duration in check below
        nd_time = session.nd_params['on'] + session.nd_params['off']
        nd_time *= scan_duration / max(session.nd_params['period'], scan_duration)
        nd_time = nd_time if session.nd_params['period'] >= 0 else 0.
        # Check whether the target will be visible for entire duration of raster scan
        if not session.target_visible(target, (scan_duration + nd_time) * num_scans):
            user_logger.warning("Skipping raster scan, as target '%s' will be below horizon" % (target.name,))
            return False

        # Create start and end positions of each scan, based on scan parameters
        scan_levels = np.arange(-(num_scans // 2), num_scans // 2 + 1)
        scanning_coord = (scan_extent / 2.0) * (-1) ** scan_levels
        stepping_coord = scan_spacing * scan_levels
        # Flip sign of elevation offsets to ensure that the first scan always starts at the top left of target
        scan_starts = zip(scanning_coord, -stepping_coord) if scan_in_azimuth else zip(stepping_coord, -scanning_coord)
        scan_ends = zip(-scanning_coord, -stepping_coord) if scan_in_azimuth else zip(stepping_coord, scanning_coord)

        # Perform multiple scans across the target
        for scan_index, (start, end) in enumerate(zip(scan_starts, scan_ends)):
            session.scan(target, duration=scan_duration, start=start, end=end,
                         index=scan_index, projection=projection, announce=False)
        return True

    def end(self, interrupted=False):
        """End the session, which stops data capturing and closes the data file.

        This does not affect the antennas, which continue to perform their
        last action (unless explicitly asked to stow).

        Parameters
        ----------
        interrupted : {False, True}, optional
            True if session got interrupted via an exception

        """
        try:
            # Create references to allow easy copy-and-pasting from this function
            session, ants, data, katsys = self, self.ants, self.data, self.kat.sys

            # XXX still relevant? -> via [capture_done]
            # # Obtain the name of the file currently being written to
            # reply = data.req.k7w_get_current_file()
            # outfile = reply[1].replace('writing', 'unaugmented') if reply.succeeded else '<unknown file>'
            # user_logger.info('Scans complete, data captured to %s' % (outfile,))
            # # The final output file name after augmentation
            # session.output_file = os.path.basename(outfile).replace('.unaugmented', '')

            # Stop the data flow
            data.req.capture_stop(self.product)
            # Stop streaming KATCP sensor updates to the capture thread
            # data.req.katcp2spead_stop_stream()
            user_logger.info('Ended data capturing session with experiment ID %s' % (session.experiment_id,))
            katsys.req.set_script_param('script-endtime', time.time())
            katsys.req.set_script_param('script-status', 'interrupted' if interrupted else 'completed')
            activity_logger.info('Ended data capturing session (%s) with experiment ID %s' %
                                 ('interrupted' if interrupted else 'completed', session.experiment_id,))

            if session.stow_when_done and self.ants is not None:
                user_logger.info('stowing dishes')
                activity_logger.info('Stowing dishes')
                ants.req.mode('STOW')

            user_logger.info('==========================')

        finally:
            # Disable logging to HDF5 file
            user_logger.removeHandler(self._script_log_handler)
            # Finally close the HDF5 file and prepare for augmentation after all logging and parameter settings are done
            data.req.capture_done(self.product)
            activity_logger.info("----- Script ended  %s (%s)" % (sys.argv[0], ' '.join(sys.argv[1:])))


class TimeSession(CaptureSessionBase):
    """Fake CaptureSession object used to estimate the duration of an experiment."""
    def __init__(self, kat, product=None, dump_rate=1.0, **kwargs):
        self.kat = kat
        self.data = kat.data_rts

        # Default settings for session parameters (in case standard_setup is not called)
        self.ants = None
        self.experiment_id = 'interactive'
        self.stow_when_done = False
        self.nd_params = {'diode': 'coupler', 'on': 0., 'off': 0., 'period': -1.}
        self.last_nd_firing = 0.
        self.output_file = ''
        self.dump_period = self._requested_dump_period = 1.0 / dump_rate
        self.horizon = 3.0

        self.start_time = self._end_of_previous_session = time.time()
        self.time = self.start_time
        self.projection = ('ARC', 0., 0.)
        # Actual antenna elevation limit (as opposed to user-requested session horizon)
        self.el_limit = 2.5

        # Usurp time module functions that deal with the passage of real time, and connect them to session time instead
        self._realtime, self._realsleep = time.time, time.sleep
        time.time = lambda: self.time
        def simsleep(seconds):
            self.time += seconds
        time.sleep = simsleep
        self._fake_ants = []

        # Modify logging so that only stream handlers are active and timestamps are prepended with a tilde
        for handler in user_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                form = handler.formatter
                form.old_datefmt = form.datefmt
                form.datefmt = 'DRY-RUN: ' + (form.datefmt if form.datefmt else '%Y-%m-%d %H:%M:%S')
            else:
                handler.old_level = handler.level
                handler.setLevel(100)

        user_logger.info('Estimating duration of experiment starting now (nothing real will happen!)')
        user_logger.info('==========================')
        user_logger.info('New data capturing session')
        user_logger.info('--------------------------')
        user_logger.info("Data proxy used = %s" % (self.data.name,))
        if product is None:
            user_logger.info('Data product = unknown to simulator')
        else:
            user_logger.info('Data product = %s' % (product,))

        activity_logger.info("Timing simulation. ----- Script starting %s (%s). Output file None" % (sys.argv[0], ' '.join(sys.argv[1:])))

    def __enter__(self):
        """Start time estimate, overriding the time module."""
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Finish time estimate, restoring the time module."""
        self.end()
        # Do not suppress any exceptions that occurred in the body of with-statement
        return False

    def _azel(self, target, timestamp, antenna):
        """Target (az, el) position in degrees (including offsets in degrees)."""
        projection_type, x, y = self.projection
        az, el = target.plane_to_sphere(katpoint.deg2rad(x), katpoint.deg2rad(y), timestamp, antenna, projection_type)
        return katpoint.rad2deg(az), katpoint.rad2deg(el)

    def _teleport_to(self, target, mode='POINT'):
        """Move antennas instantaneously onto target (or nearest point on horizon)."""
        for m in range(len(self._fake_ants)):
            antenna = self._fake_ants[m][0]
            az, el = self._azel(target, self.time, antenna)
            self._fake_ants[m] = (antenna, mode, az, max(el, self.el_limit))

    def _slew_to(self, target, mode='POINT', timeout=300.):
        """Slew antennas to target (or nearest point on horizon), with timeout."""
        slew_times = []
        for ant, ant_mode, ant_az, ant_el in self._fake_ants:
            def estimate_slew(timestamp):
                """Obtain instantaneous target position and estimate time to slew there."""
                # Target position right now
                az, el = self._azel(target, timestamp, ant)
                # If target is below horizon, aim at closest point on horizon
                az_dist, el_dist = np.abs(az - ant_az), np.abs(max(el, self.el_limit) - ant_el)
                # Ignore azimuth wraps and drive strategies
                az_dist = az_dist if az_dist < 180. else 360. - az_dist
                # Assume az speed of 2 deg/s, el speed of 1 deg/s and overhead of 1 second
                slew_time = max(0.5 * az_dist, 1.0 * el_dist) + 1.0
                return az, el, slew_time
            # Initial estimate of slew time, based on a stationary target
            az1, el1, slew_time = estimate_slew(self.time)
            # Crude adjustment for target motion: chase target position for 2 iterations
            az2, el2, slew_time = estimate_slew(self.time + slew_time)
            az2, el2, slew_time = estimate_slew(self.time + slew_time)
            # Ensure slew does not take longer than timeout
            slew_time = min(slew_time, timeout)
            # If source is below horizon, handle timeout and potential rise in that interval
            if el2 < self.el_limit:
                # Position after timeout
                az_after_timeout, el_after_timeout = self._azel(target, self.time + timeout, ant)
                # If source is still down, slew time == timeout, else estimate rise time through linear interpolation
                slew_time = (self.el_limit - el1) / (el_after_timeout - el1) * timeout \
                            if el_after_timeout > self.el_limit else timeout
                az2, el2 = self._azel(target, self.time + slew_time, ant)
                el2 = max(el2, self.el_limit)
            slew_times.append(slew_time)
#            print "%s slewing from (%.1f, %.1f) to (%.1f, %.1f) in %.1f seconds" % \
#                  (ant.name, ant_az, ant_el, az2, el2, slew_time)
        # The overall slew time is the max for all antennas - adjust current time to reflect the slew
        self.time += (np.max(slew_times) if len(slew_times) > 0 else 0.)
        # Blindly assume all antennas are on target (or on horizon) after this interval
        self._teleport_to(target, mode)

    def get_centre_freq(self):
        """Get RF (sky) frequency associated with middle CBF channel.

        Returns
        -------
        centre_freq : float
            Actual centre frequency in MHz

        """
        return 1284.0

    def set_centre_freq(self, centre_freq):
        """Set RF (sky) frequency associated with middle CBF channel.

        Parameters
        ----------
        centre_freq : float
            Desired centre frequency in MHz

        """
        pass

    def standard_setup(self, observer, description, experiment_id=None,
                       centre_freq=None, nd_params=None,
                       stow_when_done=None, horizon=None, no_mask=False, **kwargs):
        """Perform basic experimental setup including antennas, LO and dump rate."""
        self.ants = ant_array(self.kat, self.get_ant_names())
        for ant in self.ants:
            try:
                self._fake_ants.append((katpoint.Antenna(ant.sensor.observer.get_value()),
                                        ant.sensor.mode.get_value(),
                                        ant.sensor.pos_actual_scan_azim.get_value(),
                                        ant.sensor.pos_actual_scan_elev.get_value()))
            except AttributeError:
                pass
        # Override provided session parameters (or initialize them from existing parameters if not provided)
        self.experiment_id = experiment_id = self.experiment_id if experiment_id is None else experiment_id
        self.nd_params = nd_params = self.nd_params if nd_params is None else nd_params
        self.stow_when_done = stow_when_done = self.stow_when_done if stow_when_done is None else stow_when_done
        self.horizon = self.horizon if horizon is None else horizon

        user_logger.info('Antennas used = %s' % (' '.join([ant[0].name for ant in self._fake_ants]),))
        user_logger.info('Observer = %s' % (observer,))
        user_logger.info("Description ='%s'" % (description,))
        user_logger.info('Experiment ID = %s' % (experiment_id,))
        # There is no way to find out the centre frequency in this fake session... maybe
        centre_freq = self.get_centre_freq()
        if centre_freq is None:
            user_logger.info('RF centre frequency = unknown to simulator, dump rate = %g Hz' % (1.0 / self.dump_period,))
        else:
            user_logger.info('RF centre frequency = %g MHz, dump rate = %g Hz' % (centre_freq, 1.0 / self.dump_period))
        if nd_params['period'] > 0:
            nd_info = "Will switch '%s' noise diode on for %g s and off for %g s, every %g s if possible" % \
                      (nd_params['diode'], nd_params['on'], nd_params['off'], nd_params['period'])
        elif nd_params['period'] == 0:
            nd_info = "Will switch '%s' noise diode on for %g s and off for %g s at every opportunity" % \
                      (nd_params['diode'], nd_params['on'], nd_params['off'])
        else:
            nd_info = "Noise diode will not fire automatically"
        user_logger.info(nd_info + " while performing canned commands")
        user_logger.info('--------------------------')

    def capture_start(self):
        """Starting capture has no timing effect."""
        pass

    def label(self, label):
        """Adding label has no timing effect."""
        if label:
            user_logger.info("New compound scan: '%s'" % (label,))

    def on_target(self, target):
        """Determine whether antennas are tracking a given target."""
        if not self._fake_ants:
            return False
        for antenna, mode, ant_az, ant_el in self._fake_ants:
            az, el = self._azel(target, self.time, antenna)
            # Checking for lock and checking for target identity considered the same thing
            if (az != ant_az) or (el != ant_el) or (mode != 'POINT'):
                return False
        return True

    def target_visible(self, target, duration=0., timeout=300., operation='scan'):
        """Check whether target is visible for given duration."""
        if not self._fake_ants:
            return False
        # Convert description string to target object, or keep object as is
        target = target if isinstance(target, katpoint.Target) else katpoint.Target(target)
        horizon = katpoint.deg2rad(self.horizon)
        # Include an average time to slew to the target (worst case about 90 seconds, so half that)
        now = self.time + 45.
        average_el, visible_before, visible_after = [], [], []
        for antenna, mode, ant_az, ant_el in self._fake_ants:
            az, el = target.azel(now, antenna)
            average_el.append(katpoint.rad2deg(el))
            # If not up yet, see if the target will pop out before the timeout
            if el < horizon:
                now += timeout
                az, el = target.azel(now, antenna)
            visible_before.append(el >= horizon)
            # Check what happens at end of observation
            az, el = target.azel(now + duration, antenna)
            visible_after.append(el >= horizon)
        if all(visible_before) and all(visible_after):
            return True
        always_invisible = any(~np.array(visible_before) & ~np.array(visible_after))
        if always_invisible:
            user_logger.warning("Target '%s' is never up during requested period (average elevation is %g degrees)" %
                                (target.name, np.mean(average_el)))
        else:
            user_logger.warning("Target '%s' will rise or set during requested period" % (target.name,))
        return False

    def fire_noise_diode(self, diode='coupler', on=10.0, off=10.0, period=0.0, align=True, announce=True):
        """Estimate time taken to fire noise diode."""
        return False
        # XXX needs a rethink
        # if not self._fake_ants:
        #     raise ValueError('No antennas specified for session - please run session.standard_setup first')
        # if self.dump_period == 0.0:
        #     # Wait for the first correlator dump to appear
        #     user_logger.info('waiting for correlator dump to arrive')
        #     self.dump_period = self._requested_dump_period
        #     time.sleep(self.dump_period)
        #     user_logger.info('correlator dump arrived')
        # if period < 0.0 or (self.time - self.last_nd_firing) < period:
        #     return False
        # if announce:
        #     user_logger.info("Firing '%s' noise diode (%g seconds on, %g seconds off)" % (diode, on, off))
        # else:
        #     user_logger.info('firing noise diode')
        # self.time += on
        # self.last_nd_firing = self.time + 0.
        # self.time += off
        # user_logger.info('fired noise diode')
        # return True

    def set_target(self, target):
        """Setting target has no timing effect."""
        if not self._fake_ants:
            raise ValueError('No antennas specified for session - please run session.standard_setup first')

    def track(self, target, duration=20.0, announce=True):
        """Estimate time taken to perform track."""
        if not self._fake_ants:
            raise ValueError('No antennas specified for session - please run session.standard_setup first')
        target = target if isinstance(target, katpoint.Target) else katpoint.Target(target)
        if announce:
            user_logger.info("Initiating %g-second track on target '%s'" % (duration, target.name))
        if not self.target_visible(target, duration):
            user_logger.warning("Skipping track, as target '%s' will be below horizon" % (target.name,))
            return False
        self.fire_noise_diode(announce=False, **self.nd_params)
        if not self.on_target(target):
            user_logger.info('slewing to target')
            self._slew_to(target)
            user_logger.info('target reached')
            self.fire_noise_diode(announce=False, **self.nd_params)
        user_logger.info('tracking target')
        self.time += duration + 1.0
        user_logger.info('target tracked for %g seconds' % (duration,))
        self.fire_noise_diode(announce=False, **self.nd_params)
        self._teleport_to(target)
        return True

    def scan(self, target, duration=30.0, start=(-3.0, 0.0), end=(3.0, 0.0),
             index=-1, projection=default_proj, announce=True):
        """Estimate time taken to perform single linear scan."""
        if not self._fake_ants:
            raise ValueError('No antennas specified for session - please run session.standard_setup first')
        scan_name = 'scan' if index < 0 else 'scan %d' % (index,)
        target = target if isinstance(target, katpoint.Target) else katpoint.Target(target)
        if announce:
            user_logger.info("Initiating %g-second scan across target '%s'" % (duration, target.name))
        if not self.target_visible(target, duration):
            user_logger.warning("Skipping track, as target '%s' will be below horizon" % (target.name,))
            return False
        self.fire_noise_diode(announce=False, **self.nd_params)
        projection = Offset.PROJECTIONS[projection]
        self.projection = (projection, start[0], start[1])
        user_logger.info('slewing to start of %s' % (scan_name,))
        self._slew_to(target, mode='SCAN')
        user_logger.info('start of %s reached' % (scan_name,))
        self.fire_noise_diode(announce=False, **self.nd_params)
        # Assume antennas can keep up with target (and doesn't scan too fast either)
        user_logger.info('performing %s' % (scan_name,))
        self.time += duration + 1.0
        user_logger.info('%s complete' % (scan_name,))
        self.fire_noise_diode(announce=False, **self.nd_params)
        self.projection = (projection, end[0], end[1])
        self._teleport_to(target)
        return True

    def raster_scan(self, target, num_scans=3, scan_duration=30.0, scan_extent=6.0, scan_spacing=0.5,
                    scan_in_azimuth=True, projection=default_proj, announce=True):
        """Estimate time taken to perform raster scan."""
        if not self._fake_ants:
            raise ValueError('No antennas specified for session - please run session.standard_setup first')
        target = target if isinstance(target, katpoint.Target) else katpoint.Target(target)
        projection = Offset.PROJECTIONS[projection]
        if announce:
            user_logger.info("Initiating raster scan (%d %g-second scans extending %g degrees) on target '%s'" %
                             (num_scans, scan_duration, scan_extent, target.name))
        nd_time = self.nd_params['on'] + self.nd_params['off']
        nd_time *= scan_duration / max(self.nd_params['period'], scan_duration)
        nd_time = nd_time if self.nd_params['period'] >= 0 else 0.
        if not self.target_visible(target, (scan_duration + nd_time) * num_scans):
            user_logger.warning("Skipping track, as target '%s' will be below horizon" % (target.name,))
            return False
        # Create start and end positions of each scan, based on scan parameters
        scan_levels = np.arange(-(num_scans // 2), num_scans // 2 + 1)
        scanning_coord = (scan_extent / 2.0) * (-1) ** scan_levels
        stepping_coord = scan_spacing * scan_levels
        # Flip sign of elevation offsets to ensure that the first scan always starts at the top left of target
        scan_starts = zip(scanning_coord, -stepping_coord) if scan_in_azimuth else zip(stepping_coord, -scanning_coord)
        scan_ends = zip(-scanning_coord, -stepping_coord) if scan_in_azimuth else zip(stepping_coord, scanning_coord)
        self.fire_noise_diode(announce=False, **self.nd_params)
        # Perform multiple scans across the target
        for scan_index, (start, end) in enumerate(zip(scan_starts, scan_ends)):
            self.projection = (projection, start[0], start[1])
            user_logger.info('slewing to start of scan %d' % (scan_index,))
            self._slew_to(target, mode='SCAN')
            user_logger.info('start of scan %d reached' % (scan_index,))
            self.fire_noise_diode(announce=False, **self.nd_params)
            # Assume antennas can keep up with target (and doesn't scan too fast either)
            user_logger.info('performing scan %d' % (scan_index,))
            self.time += scan_duration + 1.0
            user_logger.info('scan %d complete' % (scan_index,))
            self.fire_noise_diode(announce=False, **self.nd_params)
            self.projection = (projection, end[0], end[1])
            self._teleport_to(target)
        return True

    def end(self):
        """Stop data capturing to shut down the session and close the data file."""
        user_logger.info('Scans complete, no data captured as this is a timing simulation...')
        user_logger.info('Ended data capturing session with experiment ID %s' % (self.experiment_id,))
        activity_logger.info('Timing simulation. Ended data capturing session with experiment ID %s' % (self.experiment_id,))

        if self.stow_when_done and self._fake_ants:
            user_logger.info("Stowing dishes.")
            activity_logger.info('Timing simulation. Stowing dishes.')
            self._teleport_to(katpoint.Target("azel, 0.0, 90.0"), mode="STOW")
        user_logger.info('==========================')
        duration = self.time - self.start_time
        # Let KATCoreConn know how long the estimated observation time was.
        self.kat.set_estimated_duration(duration)
        if duration <= 100:
            duration = '%d seconds' % (np.ceil(duration),)
        elif duration <= 100 * 60:
            duration = '%d minutes' % (np.ceil(duration / 60.),)
        else:
            duration = '%.1f hours' % (duration / 3600.,)
        msg = "Experiment estimated to last %s until this time" % (duration,)
        user_logger.info(msg + "\n")
        activity_logger.info("Timing simulation. %s" % (msg,))
        # Restore time module functions
        time.time, time.sleep = self._realtime, self._realsleep
        # Restore logging
        for handler in user_logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.formatter.datefmt = handler.formatter.old_datefmt
                del handler.formatter.old_datefmt
            else:
                handler.setLevel(handler.old_level)
                del handler.old_level

        activity_logger.info("Timing simulation. ----- Script ended %s (%s). Output file None" % (sys.argv[0], ' '.join(sys.argv[1:])))
