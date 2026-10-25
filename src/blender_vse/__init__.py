"""Public package for revision-safe Blender VSE control."""

from .api import BlenderVSE
from .catalog import PUBLIC_OPERATIONS, operation_catalog
from .context import CONTEXT_POLICY, ReadQuery
from .resume import ResumeCapsuleError, build_resume_capsule
from .blender import (
    available_ops,
    blender_execute,
    environment_report,
    find_blender,
)
from .router import available_ops_report, router_execute

__all__ = [
    "BlenderVSE",
    "CONTEXT_POLICY",
    "PUBLIC_OPERATIONS",
    "ReadQuery",
    "ResumeCapsuleError",
    "available_ops",
    "available_ops_report",
    "blender_execute",
    "build_resume_capsule",
    "environment_report",
    "find_blender",
    "operation_catalog",
    "router_execute",
]

__version__ = "0.2.0"
