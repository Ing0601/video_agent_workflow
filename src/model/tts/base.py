import functools
import inspect
import logging
import random
import threading
import time
import warnings
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, TypeVar, Union

from pydantic import BaseModel, Field

from ...logger.logging import logger as default_logger


# Thread-safe lock for ManagerMixin
_lock = threading.RLock()
T = TypeVar("T")


def _acquire_lock() -> None:
    """Acquires the module-level lock for serializing access to shared data."""
    if _lock:
        _lock.acquire()


def _release_lock() -> None:
    """Releases the module-level lock acquired by calling _acquire_lock()."""
    if _lock:
        _lock.release()


class ManagerMeta(type):
    """The metaclass for global accessible class.

    The subclasses inheriting from ``ManagerMeta`` will manage their
    own ``_instance_dict`` and root instances. The constructors of subclasses
    must contain the ``name`` argument.
    """

    _instance_dict: Dict[str, Any] = OrderedDict()

    def __init__(cls: Type[Any], *args: Any) -> None:
        cls._instance_dict = OrderedDict()
        params = inspect.getfullargspec(cls)
        params_names: List[str] = params[0] if params[0] else []
        assert "name" in params_names, f"{cls} must have the `name` argument"
        super().__init__(*args)


class ManagerMixin(metaclass=ManagerMeta):
    """Base class for managing singleton instances with global access.

    The subclasses inheriting from ``ManagerMixin`` can get their
    global instances.

    Examples:
        >>> class GlobalAccessible(ManagerMixin):
        >>>     def __init__(self, name=''):
        >>>         super().__init__(name)
        >>>
        >>> GlobalAccessible.get_instance('name')
        >>> instance_1 = GlobalAccessible.get_instance('name')
        >>> instance_2 = GlobalAccessible.get_instance('name')
        >>> assert id(instance_1) == id(instance_2)
    """

    def __init__(self, name: str = "", **kwargs: Any) -> None:
        assert isinstance(name, str) and name, "name argument must be an non-empty string."
        self._instance_name = name
        # Register instance in _instance_dict if not already present
        _acquire_lock()
        if name not in self._instance_dict:  # type: ignore
            self._instance_dict[name] = self  # type: ignore
        _release_lock()

    @classmethod
    def get_instance(cls: ManagerMeta, name: str, force_create: bool = False, **kwargs: Any) -> Any:
        """Gets subclass instance by name if the name exists.

        If corresponding name instance has not been created, ``get_instance``
        will create an instance, otherwise ``get_instance`` will return the
        corresponding instance.
        """
        _acquire_lock()
        assert isinstance(name, str), f"type of name should be str, but got {type(cls)}"
        instance_dict = cls._instance_dict
        # Get the instance by name.
        if name not in instance_dict:
            instance = cls(name=name, **kwargs)
            instance_dict[name] = instance
        elif force_create:
            instance = cls(name=name, **kwargs)
            instance_dict.pop(name)
            instance_dict[name] = instance
        elif kwargs:
            warnings.warn(
                f"{cls} instance named of {name} has been created, "
                "the method `get_instance` should not accept any other arguments"
            )
        _release_lock()
        return instance_dict[name]

    @classmethod
    def get_current_instance(cls: ManagerMeta) -> Any:
        """Gets latest created instance."""
        _acquire_lock()
        if not cls._instance_dict:
            raise RuntimeError(
                f"Before calling {cls.__name__}.get_current_instance(), you "
                "should call get_instance(name=xxx) at least once."
            )
        name = next(iter(reversed(cls._instance_dict)))
        _release_lock()
        return cls._instance_dict[name]

    @classmethod
    def check_instance_created(cls: ManagerMeta, name: str) -> bool:
        """Checks whether the name corresponding instance exists."""
        return name in cls._instance_dict

    @property
    def instance_name(self) -> str:
        """Gets the name of instance."""
        return self._instance_name

    @classmethod
    def list_instances(cls: ManagerMeta) -> List[str]:
        """Lists all instances of the class."""
        return list(cls._instance_dict.keys())


def _perform_retry(
    func: Callable,
    args: Tuple,
    kwargs: dict,
    max_retries: int,
    get_delay: Callable[[int], float],
    should_retry: Callable[[Exception], bool],
    error_types: Tuple[Type[Exception], ...],
    raise_error: bool = True,
    verbose: bool = True,
    logger=None,
) -> Any:
    """Core retry logic shared between retry decorators."""
    last_exception = None

    for retry_count in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except error_types as e:
            last_exception = e

            # Check if we should retry based on the exception
            if not should_retry(e):
                if verbose:
                    if logger:
                        logger.warning(f"Not retrying {func.__name__} due to non-retryable exception: {str(e)}")
                    else:
                        print(f"Not retrying {func.__name__} due to non-retryable exception: {str(e)}")
                if raise_error:
                    raise e
                else:
                    return None

            if retry_count >= max_retries:
                if verbose:
                    if logger:
                        logger.warning(f"Maximum retries ({max_retries}) reached for {func.__name__}")
                    else:
                        print(f"Maximum retries ({max_retries}) reached for {func.__name__}")
                if raise_error:
                    raise last_exception
                else:
                    return None

            # Calculate delay for this retry
            delay = get_delay(retry_count)

            if verbose:
                if logger:
                    logger.info(
                        f"Retry {retry_count + 1}/{max_retries} for {func.__name__} "
                        f"after {delay:.2f}s due to: {str(e)}"
                    )
                else:
                    print(
                        f"Retry {retry_count + 1}/{max_retries} for {func.__name__} "
                        f"after {delay:.2f}s due to: {str(e)}"
                    )

            time.sleep(delay)

    if last_exception:
        if raise_error:
            raise last_exception
        else:
            return None

    if raise_error:
        raise RuntimeError(f"Unexpected error in retry logic for {func.__name__}")
    return None


def retry_with_exponential_backoff(
    max_retries_func: Callable[[Any], int] = lambda _: 3,
    initial_delay_func: Callable[[Any], float] = lambda _: 1.0,
    max_delay_func: Callable[[Any], float] = lambda _: 60.0,
    backoff_factor_func: Callable[[Any], float] = lambda _: 2.0,
    jitter: bool = True,
    error_types: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception,
    should_retry_func: Optional[Callable[[Exception], bool]] = None,
    raise_error_func: Callable[[Any], bool] = lambda _: True,
    verbose: bool = True,
):
    """Advanced retry decorator with exponential backoff and jitter.

    This advanced retry decorator takes function parameters that can
    access the instance of the class by using `self`.

    Args:
        max_retries_func: Function that takes self and returns max retries
        initial_delay_func: Function that takes self and returns initial delay
        max_delay_func: Function that takes self and returns max delay
        backoff_factor_func: Function that takes self and returns the backoff factor
        jitter: Whether to add random jitter to delay
        error_types: Exception types to catch and retry
        should_retry_func: Optional function that takes an exception and returns
            whether to retry based on the exception
        raise_error_func: Function that takes self and returns whether to raise
            the last exception if all retries fail.
        verbose: Whether to print the retry information.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            # Get configuration from instance
            max_retries = max_retries_func(self)
            initial_delay = initial_delay_func(self)
            max_delay = max_delay_func(self)
            raise_error = raise_error_func(self)
            backoff_factor = backoff_factor_func(self)

            # Define delay calculation function with jitter
            def get_delay(retry_count: int) -> float:
                base_delay = initial_delay * (backoff_factor ** retry_count)
                if jitter:
                    jittered_delay = base_delay * (1 + random.random() * 0.1)
                    return min(max_delay, jittered_delay)
                else:
                    return min(max_delay, base_delay)

            actual_should_retry = should_retry_func or (lambda _: True)

            actual_error_types = error_types
            if not isinstance(actual_error_types, tuple):
                actual_error_types = (actual_error_types,)

            # Use instance logger if available
            instance_logger = getattr(self, "_logger", default_logger)

            return _perform_retry(
                func=func,
                args=(self,) + args,
                kwargs=kwargs,
                max_retries=max_retries,
                get_delay=get_delay,
                should_retry=actual_should_retry,
                error_types=actual_error_types,
                logger=instance_logger,
                verbose=verbose,
                raise_error=raise_error,
            )

        return wrapper

    return decorator


class TTSModelConfig(BaseModel):
    """Configuration class for TTS models.

    Combines retry configuration with TTS-specific settings in a unified way,
    similar to QwenClientConfig pattern.
    """

    # Retry configuration
    max_retries: int = Field(3, description="Maximum number of retry attempts")
    retry_delay: float = Field(1.0, description="Initial delay between retries in seconds")
    retry_max_delay: float = Field(30.0, description="Maximum delay between retries in seconds")
    retry_backoff: float = Field(2.0, description="Backoff multiplier for exponential backoff")

    # Common TTS configuration (can be overridden by specific implementations)
    app_id: str = Field("", description="Application ID for TTS service")
    access_token: str = Field("", description="Access token for TTS service")
    secret_key: str = Field("", description="Secret key for TTS service")
    http_url: str = Field("", description="HTTP URL for TTS service")
    voice_type: str = Field("", description="Voice type identifier")
    speed_ratio: float = Field(1.0, description="Speech speed ratio")
    sample_rate: int = Field(24000, description="Audio sample rate")
    encoding: str = Field("mp3", description="Audio encoding format")

    # Text splitting configuration
    max_text_bytes: int = Field(1024, description="Maximum text bytes per chunk")
    min_chunk_ratio: float = Field(0.3, description="Minimum chunk size ratio")
    auto_split: bool = Field(True, description="Enable automatic text splitting for long texts")
    chunk_delay: float = Field(0.5, description="Delay between chunks in seconds")

    class Config:
        extra = "allow"  # Allow additional fields for specific TTS implementations


class BaseTTSModel(ManagerMixin):
    """Base class for TTS models, providing common functionality
    for both local and remote models.

    Args:
        name (str): The name of the TTS model, which is used to identify
            the TTS model.
        config (Optional[Dict[str, Any]]): The configuration of the TTS model.
        api_key (Optional[str]): The API key of the TTS model.
        logger (Optional[logging.Logger]): The logger of the TTS model.
    """

    def __init__(
        self,
        name: str,
        config: Optional[Dict[str, Any]] = None,
        api_key: Optional[str] = None,
        logger=None,
    ):
        super().__init__(name)
        self.config = self._create_config(config or {}, api_key)
        self._logger = logger or default_logger

    def _create_config(
        self, config: Dict[str, Any], api_key: Optional[str] = None
    ) -> TTSModelConfig:
        """Creates a TTSModelConfig instance from the provided configuration.

        This method follows the QwenClient pattern for unified configuration handling.

        Args:
            config: Configuration dictionary.
            api_key: Optional API key that overrides config.

        Returns:
            TTSModelConfig: Validated configuration instance.
        """
        # Merge API key into config if provided
        if api_key:
            config = config.copy()
            config["access_token"] = api_key

        return TTSModelConfig(**config)

    @retry_with_exponential_backoff(
        max_retries_func=lambda self: self.config.max_retries,
        initial_delay_func=lambda self: self.config.retry_delay,
        max_delay_func=lambda self: self.config.retry_max_delay,
        backoff_factor_func=lambda self: self.config.retry_backoff,
    )
    def synthesize(
        self,
        text: str,
        output_path: Union[str, Path],
        **kwargs,
    ) -> bool:
        """Synthesizes input text to audio with timestamps.

        Args:
            text (str): The text to synthesize.
            output_path (str | Path): The path where the audio file will be saved.
            **kwargs: Additional keyword arguments to pass to the TTS model.

        Returns:
            bool: True if synthesis was successful, False otherwise.
        """
        raise NotImplementedError("Subclasses should implement this method.")