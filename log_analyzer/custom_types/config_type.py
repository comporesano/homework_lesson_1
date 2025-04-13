from os import PathLike
from typing import TypedDict, Union


class ConfigType(TypedDict):
    REPORT_SIZE: Union[str, PathLike[str]]
    REPORT_DIR: Union[str, PathLike[str]]
    LOG_DIR: Union[str, PathLike[str]]
    CACHE_DIR: Union[str, PathLike[str]]
    APP_LOG_DIR: Union[str, PathLike[str]]
    APP_LOG_FILE: Union[str, PathLike[str]]
