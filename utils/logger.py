from enum import Enum
import logging
import colorlog

from constants import DEBUG_LOG_ENABLED

class LoggingType(Enum):
    DEBUG = 'debug'
    INFO = 'info'
    WARNING = 'warning'
    ERROR = 'error'
    CRITICAL = 'critical'

class Logger(logging.Logger):
    def __init__(self, name='app_logger', log_file=None, log_level=logging.DEBUG):
        super().__init__(name, log_level)
        self.log_file = log_file

        self._configure_logging()

    def _configure_logging(self):
        log_formatter = colorlog.ColoredFormatter(
            '%(log_color)s%(levelname)s:%(name)s:%(message)s',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            },
            reset=True,
            secondary_log_colors={},
            style='%'
        )
        if self.log_file:
            file_handler = logging.FileHandler(self.log_file)
            file_handler.setFormatter(log_formatter)
            self.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        self.addHandler(console_handler)

    def log(self, log_type: LoggingType, log_message, log_data = None):
        if log_type == LoggingType.DEBUG and DEBUG_LOG_ENABLED:
            self.debug(log_message)
        elif log_type == LoggingType.INFO:
            self.info(log_message)
        elif log_type == LoggingType.ERROR:
            self.error(log_message)
        elif log_type == LoggingType.WARNING:
            self.warning(log_message)

app_logger = Logger()