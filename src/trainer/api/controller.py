from trainer.api.controllers.recordings import RecordingControllerMixin
from trainer.api.dependencies import ApiDependenciesMixin
from trainer.api.transport import ApiTransportMixin


class ApiController(
    RecordingControllerMixin,
    ApiDependenciesMixin,
    ApiTransportMixin,
):
    pass
