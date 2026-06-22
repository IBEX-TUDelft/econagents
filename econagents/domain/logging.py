import logging
from typing import Optional


class LoggerMixin:
    """
    A mixin that provides standardized logger functionality.

    This mixin makes logger initialization optional and provides:
    - A default logger if none is set
    - Property getter/setter for logger management
    - Consistent logging interface across components
    """

    _logger: Optional[logging.Logger] = None

    @property
    def logger(self) -> logging.Logger:
        """
        Get the logger instance. Creates a default logger if none is set.

        Returns:
            logging.Logger: The logger instance
        """
        if self._logger is None:
            # Create a default logger with the class name
            self._logger = logging.getLogger(self.__class__.__name__)
            # Add basic handler if no handlers present
            if not self._logger.handlers:
                handler = logging.StreamHandler()
                formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
                handler.setFormatter(formatter)
                self._logger.addHandler(handler)
                self._logger.setLevel(logging.INFO)
        return self._logger

    @logger.setter
    def logger(self, logger: logging.Logger) -> None:
        """
        Set a custom logger.

        Args:
            logger: The logger instance to use
        """
        self._logger = logger
