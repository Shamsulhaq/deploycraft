"""Stack implementations for different application frameworks.

Importing this module registers all available stacks via the @register decorator.
"""

from deploycraft.stacks.base import (  # noqa: F401
    STACK_CHOICES,
    BaseStack,
    DetectedServices,
    StackContext,
    StackType,
    get_available_stacks,
    get_stack_class,
)

# Import all stacks to trigger their @register decorators
from deploycraft.stacks.django import DjangoStack  # noqa: F401
from deploycraft.stacks.fastapi import FastAPIStack  # noqa: F401
from deploycraft.stacks.html import HTMLStack  # noqa: F401
from deploycraft.stacks.nextjs import NextJSStack  # noqa: F401
from deploycraft.stacks.react import ReactCRAStack  # noqa: F401
from deploycraft.stacks.react_vite import ReactViteStack  # noqa: F401
