###############################################################################
# SKA South Africa (http://ska.ac.za/)                                        #
# Author: cam@ska.ac.za                                                       #
# Copyright @ 2013 SKA SA. All rights reserved.                               #
#                                                                             #
# THIS SOFTWARE MAY NOT BE COPIED OR DISTRIBUTED IN ANY FORM WITHOUT THE      #
# WRITTEN PERMISSION OF SKA SA.                                               #
###############################################################################
"""Define client API used when interacting with MeerKAT and other KAT-like telescopes.

This is the KATResource API as identified in the document: CAM Design Description -
MeerKAT Subarrays
"""

import abc
import collections

from katcp import katcp_resource

class KATResource(katcp_resource.KATCPResource):
    """Abstract base class defining KATResource API.

    Abstract since it inherits from katcp.katcp_resource.KATCPResource.

    KATResource API as identified in the document: CAM Design Description - MeerKAT
    Subarrays

    All the KATResourceClient instance contained by a KATResource instance should be
    available as attributes. It is expected that receptors will be available as their
    receptor names (e.g. m000 through m063), while data products will be available as
    data_<product_name>. See also the `receptors` and `data` properties.
    """

    @abc.abstractmethod
    def time(self):
        """Return the current telescope time in seconds since the Epoch.

        Mirrors time.time(), but time.time() should never be used by users of the
        telescope. Always using this time() implementation allows for accelerated-time
        telescope observation simulations (e.g. dry-running).
        """

    @abc.abstractmethod
    def sleep(self, seconds):
        """Delay execution for a given number of seconds.

        Mirrors time.sleep(), but but time.sleep() should never be used by users of the
        telescope. Always using this sleep() implementation allows for accelerated-time
        telescope observation simulations (e.g. dry-running).
        """
        # TODO consider async vs sync use cases


    StatusTuple = collections.namedtuple('StatusTuple', [
        'name', 'ip' , 'port', 'controlled', 'connected', 'status',
        'version', 'build_state', 'req_count', 'sensor_count', 'last_connected'])

    @abc.abstractmethod
    def get_status(self):
        """Status of resources in this KATResource object as a list of namedtuples.

        Returns
        -------

        list of namedtuples with fields (in order):

        name : str
            Name of the KATCP resource.
        ip : str
            IP Address of the resource's KATCP server.
        port : int
            TCP port of the resource's KATCP server.
        controlled : bool
            True if this resource is controlled.
        connected : bool
            True if the TCP connection to the resources KATCP server is open.
        status : str {"not synced", "syncing", "synced"}
            Status of device connection.
        version : str
            KATCP resource version if known.
        build_state : str
            KATCP resource build-state if known.
        req_count : int
            Number of KATCP requests available on this resource.
        sensor_count : int
            Number of sensors available on this resource.
        last_connected : float
            Last time this device was connected in telescope time seconds since the Epoch.
        """

    @abc.abstractproperty
    def user_logger(self):
        """logging.Logger instance to log telescope user messages

        This is intended chiefly for observation script usage.
        """

    @abc.abstractproperty
    def receptors(self):
        """Operations over all controlled receptors allocated to this KATResource instance

        Something akin to and katcorelib.array.Array
        """
        # TODO Decide on an actual type to use here

    @abc.abstractproperty
    def data(self):
        """Operations over all controlled data products allocated to this KATResource inst

        Something akin to the receptors property above
        """
        # TODO Decide on an actual type to use here

    @abc.abstractproperty
    def sources(self):
        """Telescope source catalogue, katpoint.Catalogue instance

        Could potentially contain sources populated from the central telescope
        configuration, and sources locally added by a telescope user.
        """

class KATResourceClient(katcp_resource.KATCPResource):
    """

    Abstract base class defining KATResourceClient API.

    Abstract since it inherits from katcp.katcp_resource.KATCPResource
    """

    @abc.abstractproperty
    def controlled(self):
        """True if this resource is controlled

        type: bool
        """

