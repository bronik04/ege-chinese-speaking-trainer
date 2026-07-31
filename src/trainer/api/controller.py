from trainer.api.controllers.materials import MaterialControllerMixin
from trainer.api.controllers.recordings import RecordingControllerMixin
from trainer.api.controllers.work import WorkControllerMixin
from trainer.api.dependencies import ApiDependenciesMixin
from trainer.api.transport import ApiTransportMixin


class ApiController(
    WorkControllerMixin,
    MaterialControllerMixin,
    RecordingControllerMixin,
    ApiDependenciesMixin,
    ApiTransportMixin,
):
    pass
