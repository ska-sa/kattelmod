###############################################################################
# SKA South Africa (http://ska.ac.za/)                                        #
# Author: cam@ska.ac.za                                                       #
# Copyright @ 2013 SKA SA. All rights reserved.                               #
#                                                                             #
# THIS SOFTWARE MAY NOT BE COPIED OR DISTRIBUTED IN ANY FORM WITHOUT THE      #
# WRITTEN PERMISSION OF SKA SA.                                               #
###############################################################################
"""Client API used when interacting with MeerKAT and other KAT-like telescopes.

This is the KATResource API as identified in the document 'CAM Design
Description - MeerKAT Subarrays'.

"""

import abc
from collections import namedtuple

from katcp.resource import KATCPResource


class KATResource(KATCPResource):
    """Abstract base class defining KATResource API.

    The KATResource API is described in the document 'CAM Design Description -
    MeerKAT Subarrays'.

    All the KATResourceClient instances contained in a KATResource instance
    should be available as attributes. It is expected that receptors will be
    available as their receptor names (e.g. m000 through m063), while data
    products will be available as data_<product_name>. See also the `receptors`
    and `data` properties.

    """

    @abc.abstractmethod
    def time(self):
        """The current telescope time in UTC seconds since the Unix epoch.

        This mirrors time.time(), but time.time() should never be called by
        users of the telescope. Always using this time() implementation allows
        for accelerated-time observation simulations (e.g. dry-running).

        """

    @abc.abstractmethod
    def sleep(self, seconds):
        """Delay execution for a given number of seconds.

        This mirrors time.sleep(), but time.sleep() should never be called by
        users of the telescope. Always using this sleep() implementation allows
        for accelerated-time observation simulations (e.g. dry-running).

        """
        # TODO consider async vs sync use cases


    class StatusTuple(namedtuple('StatusTuple',
                                 'name ip port controlled connected status '
                                 'version build_state req_count sensor_count '
                                 'last_connected')):
        """Subordinate (i.e. device/client) resource status.

        Attributes
        ----------
        name : str
            Name of the KATCP resource
        ip : str
            IP address of the resource's KATCP server
        port : int
            TCP port of the resource's KATCP server
        controlled : bool
            True if this resource is controlled by the user
        connected : bool
            True if the TCP connection to the resource's KATCP server is open
        status : {"not synced", "syncing", "synced"}
            Status of device connection
        version : str
            KATCP resource version if known
        build_state : str
            KATCP resource build-state if known
        req_count : int
            Number of KATCP requests available on this resource
        sensor_count : int
            Number of sensors available on this resource
        last_connected : float
            Timestamp indicating when this device was last connected

        """

    @abc.abstractmethod
    def get_status(self):
        """Status of subordinate resources contained in this resource.

        Returns
        -------
        status : list of :class:`StatusTuple` objects

        """

    @abc.abstractproperty
    def user_logger(self):
        """Logger object (:class:`logging.Logger`) that logs user messages.

        This is intended chiefly for observation script usage.

        """

    @abc.abstractproperty
    def receptors(self):
        """Group of all controlled receptors contained in this resource."""
        # TODO Decide on an actual type to use here (like katcorelib.array.Array)

    @abc.abstractproperty
    def data(self):
        """Group of all controlled data products contained in this resource."""
        # TODO Decide on an actual type to use here

    @abc.abstractproperty
    def targets(self):
        """Catalogue of common targets (:class:`katpoint.Catalogue` object).

        This could potentially contain targets populated from the central
        telescope configuration and sources locally added by a telescope user.

        """


class KATClientResource(KATCPResource):
    """Abstract base class defining KATClientResource API."""

    @abc.abstractproperty
    def controlled(self):
        """True if this resource is controlled by the user."""
