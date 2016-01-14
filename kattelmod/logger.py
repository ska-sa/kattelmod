import logging
import time


def make_record_with_custom_clock(self, *args):
    """Create a log record with creation timestamp produced by custom clock.

    The custom clock is set on a module level via the monkey-patched
    `logging.clock`. This object has a `time()` method that produces
    timestamps a la `time.time()`, which is the default clock. This way
    all loggers can have their clocks updated at once without iterating
    over them and reconfiguring them.

    This method should be installed into the default Logger class to have the
    best chance that all loggers will get it, even ones that have already been
    instantiated via getLogger in modules that were imported before kattelmod.
    Someone could still extend the basic Logger class and not call the base
    makeRecord() somewhere, but this is highly unlikely.

    """
    create_time = logging.clock.time()
    # Get a log record the usual way, via the monkey-patched original method
    record = self._makeRecord(*args)
    # Patch all timestamp-related fields
    record.created = create_time
    record.msecs = (create_time - long(create_time)) * 1000
    record.relativeCreated = (record.created - logging._startTime) * 1000
    return record


# Monkey-patch custom clock and makeRecord method into logging module
logging.clock = time
logging.Logger._makeRecord = logging.Logger.makeRecord
logging.Logger.makeRecord = make_record_with_custom_clock


class RobustDeliveryHandler(logging.Handler):
    """Logging handler that does robust log delivery via a function call.

    A custom function provided at initialisation is called to deliver log
    messages. In addition, a basic lock is used to avoid infinite recursion
    if the delivery mechanism fails and then attempts to log the error to
    the same handler.

    Parameters
    ----------
    deliver : function, signature `deliver(msg)`
        Function that will deliver log message to the appropriate destination

    """
    def __init__(self, deliver):
        logging.Handler.__init__(self)
        self.deliver = deliver
        self.busy_emitting = False

    def emit(self, record):
        """Emit a logging record."""
        # Do not emit from within emit()
        # This occurs when deliver() fails and logs an error itself
        if self.busy_emitting:
            return
        try:
            self.busy_emitting = True
            msg = self.format(record)
            self.deliver(msg)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)
        finally:
            self.busy_emitting = False


def configure_logging(level, script_log_cmd=None, clock=time, dry_run=False):
    """Configure logging system by setting root handlers, level and clock.

    Parameters
    ----------
    level : integer or string
        Log level for root logger (will typically apply to all loggers)
    script_log_cmd : function, signature `script_log_cmd(msg)`, optional
        Method that will deliver logs to obs component of CaptureSession
        (remove this handler by default)
    clock : time-like object, optional
        Custom clock used to timestamp all log records (default is usual clock)
    dry_run : {False, True}, optional
        True if doing a dry run, which will mark the logs as such

    """
    logging.root.setLevel(level)
    logging.clock = clock
    # Add root handler if none exists - similar to logging.basicConfig()
    if not logging.root.handlers:
        logging.root.addHandler(logging.StreamHandler())
    # Add special script log handler if not there, else update its deliverer
    # This assumes no more than one RobustDeliveryHandler on root logger
    for handler in logging.root.handlers:
        if isinstance(handler, RobustDeliveryHandler):
            if script_log_cmd:
                handler.deliver = script_log_cmd
            else:
                logging.root.removeHandler(handler)
            break
    else:
        if script_log_cmd:
            logging.root.addHandler(RobustDeliveryHandler(script_log_cmd))
    # Script log formatter has UT timestamps and indication of dry running
    fmt='%(asctime)s.%(msecs)03dZ %(name)-10s %(levelname)-8s %(message)s'
    if dry_run:
        fmt = 'DRYRUN: ' + fmt
    formatter = logging.Formatter(fmt, datefmt='%Y-%m-%d %H:%M:%S')
    formatter.converter = time.gmtime
    for handler in logging.root.handlers:
        handler.setFormatter(formatter)
