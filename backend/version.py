import os

# Semantic application version
__version__ = "1.0.0"

# Build version identifier (reads from BUILD_VERSION or Render Git Commit if available)
def get_build_version():
    custom_build = os.getenv("BUILD_VERSION")
    if custom_build:
        return custom_build
    
    commit_sha = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT")
    if commit_sha:
        return f"v{__version__}+{commit_sha[:7]}"
        
    return f"v{__version__}"

BUILD_VERSION = get_build_version()
