from trainer.api.dependencies import ApiDependenciesMixin
from trainer.api.transport import ApiTransportMixin


class ApiController(
    ApiDependenciesMixin,
    ApiTransportMixin,
):
    pass
