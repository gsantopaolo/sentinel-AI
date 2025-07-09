import lib_py.gen_types.target_coordinates_pb2 as _target_coordinates_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class RembgData(_message.Message):
    __slots__ = ("user_id", "project_id", "tile_id", "image_url", "target_coordinates", "scale", "signalr_connection_id", "origin_env")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_ID_FIELD_NUMBER: _ClassVar[int]
    TILE_ID_FIELD_NUMBER: _ClassVar[int]
    IMAGE_URL_FIELD_NUMBER: _ClassVar[int]
    TARGET_COORDINATES_FIELD_NUMBER: _ClassVar[int]
    SCALE_FIELD_NUMBER: _ClassVar[int]
    SIGNALR_CONNECTION_ID_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_ENV_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    project_id: int
    tile_id: str
    image_url: str
    target_coordinates: _target_coordinates_pb2.TargetCoordinates
    scale: float
    signalr_connection_id: str
    origin_env: str
    def __init__(self, user_id: _Optional[str] = ..., project_id: _Optional[int] = ..., tile_id: _Optional[str] = ..., image_url: _Optional[str] = ..., target_coordinates: _Optional[_Union[_target_coordinates_pb2.TargetCoordinates, _Mapping]] = ..., scale: _Optional[float] = ..., signalr_connection_id: _Optional[str] = ..., origin_env: _Optional[str] = ...) -> None: ...
