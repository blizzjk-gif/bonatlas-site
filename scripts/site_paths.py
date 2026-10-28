"""Boundaries between the marketing site and the separately deployed editor."""
from pathlib import PurePosixPath


def is_external_path(path):
    parts = PurePosixPath(path).parts
    return parts[:2] == ('atlas', 'app')


def is_disabled_path(path):
    # Host-Light serves static files; feedback currently uses Google Forms.
    return PurePosixPath(path).as_posix() == 'atlas/api/feedback.php'


def is_unmanaged_path(path):
    return is_external_path(path) or is_disabled_path(path)
