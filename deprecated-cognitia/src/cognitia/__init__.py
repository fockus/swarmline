"""cognitia — DEPRECATED, use swarmline instead."""

import warnings

warnings.warn(
    "The 'cognitia' package has been renamed to 'swarmline'. "
    "Please update your imports: 'from swarmline import ...' "
    "This compatibility wrapper will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

from swarmline import *  # noqa: F401, F403, E402
from swarmline import __version__  # noqa: F401, E402
