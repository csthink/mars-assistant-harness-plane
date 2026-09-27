"""Product execution ports. Runtime wire and domain policy remain separate authorities."""
from .host import HostExecutionPort
from .port import ExecutionPort, ExecutionError, ExecutionAuthorization
