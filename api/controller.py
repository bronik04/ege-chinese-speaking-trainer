from api.controllers.auth import AuthControllerMixin
from api.controllers.common import CommonControllerMixin
from api.controllers.groups import GroupControllerMixin
from api.controllers.materials import MaterialControllerMixin
from api.controllers.recordings import RecordingControllerMixin
from api.controllers.work import WorkControllerMixin


class ApiController(
    AuthControllerMixin,
    GroupControllerMixin,
    WorkControllerMixin,
    MaterialControllerMixin,
    RecordingControllerMixin,
    CommonControllerMixin,
):
    pass
